from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import Record
from core.testing import make_record
from orders import cart as cart_services
from orders.models import Cart, CartItem

PASSWORD = 'correct-horse-battery-staple'


def messages_of(response):
    return [str(m) for m in response.wsgi_request._messages]


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], CURRENCY_SYMBOL='€')
class CartTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.record = make_record('Blue Monday', 'New Order', 'Electronic', price=Decimal('35.00'), stock=3)
        cls.other = make_record('Computer World', 'Kraftwerk', 'Electronic', price=Decimal('48.00'), stock=1)
        cls.user = get_user_model().objects.create_user('alex', password=PASSWORD)

    def add(self, record, quantity=1, **extra):
        return self.client.post(reverse('orders:cart_add', args=[record.id]), {'quantity': quantity, **extra})

    def update(self, record, quantity):
        return self.client.post(reverse('orders:cart_update', args=[record.id]), {'quantity': quantity})

    def session_cart(self):
        return self.client.session.get(cart_services.SESSION_KEY, {})

    def saved_quantities(self, user=None):
        return cart_services.DatabaseCart(user or self.user).quantities()

    def log_in(self):
        return self.client.post(reverse('accounts:login'), {'username': 'alex', 'password': PASSWORD})


class GuestCartTests(CartTestCase):
    def test_guests_can_add_to_a_session_cart(self):
        response = self.add(self.record, 2)

        self.assertRedirects(response, reverse('orders:cart'))
        self.assertEqual(self.session_cart(), {str(self.record.pk): 2})
        self.assertFalse(Cart.objects.exists())

    def test_cart_page_and_badge_show_the_session_cart(self):
        self.add(self.record, 2)
        self.add(self.other)

        response = self.client.get(reverse('orders:cart'))

        self.assertContains(response, 'Blue Monday')
        self.assertContains(response, '€118.00')  # 2 × 35 + 48
        self.assertEqual(response.context['cart_item_count'], 3)
        self.assertContains(response, 'to save this cart to your account')

    def test_guests_must_log_in_to_check_out(self):
        self.add(self.record)

        response = self.client.get(reverse('orders:checkout'))

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('orders:checkout')}")

    def test_update_and_remove_in_the_session_cart(self):
        self.add(self.record, 1)
        self.update(self.record, 3)
        self.assertEqual(self.session_cart(), {str(self.record.pk): 3})

        self.client.post(reverse('orders:cart_remove', args=[self.record.id]))

        self.assertEqual(self.session_cart(), {})

    def test_add_can_return_to_the_page_it_came_from(self):
        response = self.add(self.record, next='/records/?q=blue')

        self.assertRedirects(response, '/records/?q=blue', fetch_redirect_response=False)

    def test_external_next_is_ignored(self):
        response = self.add(self.record, next='https://evil.example.com/')

        self.assertRedirects(response, reverse('orders:cart'))


class SavedCartTests(CartTestCase):
    def setUp(self):
        self.client.force_login(self.user)

    def test_signed_in_cart_is_saved_in_the_database(self):
        self.add(self.record, 2)
        self.add(self.record)

        self.assertEqual(self.saved_quantities(), {self.record.pk: 3})
        self.assertEqual(Cart.objects.get().user, self.user)
        self.assertNotIn(cart_services.SESSION_KEY, self.client.session)

    def test_saved_cart_survives_logging_out_and_back_in(self):
        self.add(self.record, 2)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('orders:cart')).context['cart_item_count'], 0)

        self.log_in()

        self.assertEqual(self.client.get(reverse('orders:cart')).context['cart_item_count'], 2)

    def test_carts_are_per_user(self):
        self.add(self.record)
        other = get_user_model().objects.create_user('jordan')
        self.client.force_login(other)

        self.assertEqual(self.client.get(reverse('orders:cart')).context['lines'], [])

    def test_update_to_zero_removes_the_line(self):
        self.add(self.record)

        response = self.update(self.record, 0)

        self.assertFalse(CartItem.objects.exists())
        self.assertIn('Removed "Blue Monday" from your cart.', messages_of(response))

    def test_requires_post(self):
        self.assertEqual(self.client.get(reverse('orders:cart_add', args=[self.record.id])).status_code, 405)

    def test_unknown_record_is_404(self):
        self.assertEqual(self.client.post(reverse('orders:cart_add', args=[9999]), {'quantity': 1}).status_code, 404)

    def test_invalid_quantity_is_rejected(self):
        self.add(self.record, 0)
        self.add(self.record, 'lots')

        self.assertFalse(CartItem.objects.exists())


class StockLimitTests(CartTestCase):
    def setUp(self):
        self.client.force_login(self.user)

    def test_cannot_add_more_than_stock(self):
        self.add(self.record, 2)

        response = self.add(self.record, 2)

        self.assertRedirects(response, self.record.get_absolute_url())
        self.assertEqual(self.saved_quantities(), {self.record.pk: 2})
        self.assertEqual(messages_of(response)[-1], 'Sorry, we only have 3 copies of "Blue Monday".')

    def test_last_copy_message_is_singular(self):
        self.add(self.other)

        response = self.add(self.other)

        self.assertEqual(messages_of(response)[-1], 'Sorry, we only have 1 copy of "Computer World".')

    def test_cannot_add_a_sold_out_record(self):
        Record.objects.filter(pk=self.other.pk).update(stock=0)

        response = self.add(self.other)

        self.assertEqual(messages_of(response)[-1], 'Sorry, "Computer World" is out of stock.')
        self.assertEqual(self.saved_quantities(), {})

    def test_guest_cart_has_the_same_limits(self):
        self.client.logout()

        self.add(self.record, 4)

        self.assertEqual(self.session_cart(), {})

    def test_adding_does_not_reserve_stock(self):
        self.add(self.record, 2)

        self.record.refresh_from_db()
        self.assertEqual(self.record.stock, 3)

    def test_update_above_stock_is_rejected(self):
        self.add(self.record)

        self.update(self.record, 4)

        self.assertEqual(self.saved_quantities(), {self.record.pk: 1})

    def test_cart_warns_when_stock_drops_below_the_quantity(self):
        self.add(self.record, 3)
        self.add(self.other, 1)
        Record.objects.filter(pk=self.record.pk).update(stock=1)
        Record.objects.filter(pk=self.other.pk).update(stock=0)

        response = self.client.get(reverse('orders:cart'))

        self.assertEqual([line.record for line in response.context['short_lines']], [self.record, self.other])
        self.assertContains(response, 'Stock has changed since you added these records')
        self.assertContains(response, '"Blue Monday": only 1 left and your cart has 3.')
        self.assertContains(response, '"Computer World": now sold out.')

    def test_checkout_is_blocked_until_short_lines_are_fixed(self):
        self.add(self.record, 3)
        Record.objects.filter(pk=self.record.pk).update(stock=1)

        response = self.client.get(reverse('orders:checkout'))

        self.assertRedirects(response, reverse('orders:cart'))

    def test_lowering_a_short_line_is_allowed_but_raising_it_is_not(self):
        self.add(self.record, 3)
        Record.objects.filter(pk=self.record.pk).update(stock=1)

        self.update(self.record, 2)
        self.assertEqual(self.saved_quantities(), {self.record.pk: 3})
        self.update(self.record, 1)

        self.assertEqual(self.saved_quantities(), {self.record.pk: 1})
        self.assertEqual(self.client.get(reverse('orders:cart')).context['short_lines'], [])


class CartMergeTests(CartTestCase):
    def test_session_cart_moves_into_the_saved_cart_on_login(self):
        self.add(self.record, 2)

        self.log_in()

        self.assertEqual(self.saved_quantities(), {self.record.pk: 2})
        self.assertNotIn(cart_services.SESSION_KEY, self.client.session)

    def test_quantities_are_added_to_what_was_already_saved(self):
        cart_services.DatabaseCart(self.user).add(self.record, 1)
        self.add(self.record, 1)
        self.add(self.other, 1)

        self.log_in()

        self.assertEqual(self.saved_quantities(), {self.record.pk: 2, self.other.pk: 1})

    def test_merged_quantities_are_capped_at_stock_with_a_warning(self):
        cart_services.DatabaseCart(self.user).add(self.record, 2)
        self.add(self.record, 2)

        response = self.client.post(
            reverse('accounts:login'), {'username': 'alex', 'password': PASSWORD}, follow=True
        )

        self.assertEqual(self.saved_quantities(), {self.record.pk: 3})
        self.assertContains(response, 'We only have 3 copies of &quot;Blue Monday&quot;, so your cart has 3.')

    def test_records_that_sold_out_are_not_merged(self):
        self.add(self.other)
        Record.objects.filter(pk=self.other.pk).update(stock=0)

        self.log_in()

        self.assertEqual(self.saved_quantities(), {})

    def test_deleted_records_are_dropped(self):
        self.add(self.record)
        session = self.client.session
        session[cart_services.SESSION_KEY]['999999'] = 1
        session.save()

        self.log_in()

        self.assertEqual(self.saved_quantities(), {self.record.pk: 1})

    def test_signing_up_keeps_the_guest_cart(self):
        self.add(self.record, 2)

        self.client.post(reverse('accounts:signup'), {
            'username': 'newcustomer', 'email': 'new@example.com', 'password1': PASSWORD, 'password2': PASSWORD,
        })

        new_user = get_user_model().objects.get(username='newcustomer')
        self.assertEqual(self.saved_quantities(new_user), {self.record.pk: 2})


class CartServiceTests(CartTestCase):
    def test_lines_are_in_the_order_added_with_current_prices(self):
        cart = cart_services.DatabaseCart(self.user)
        cart.add(self.other)
        cart.add(self.record, 2)
        Record.objects.filter(pk=self.record.pk).update(price=Decimal('30.00'))

        lines = cart.lines()

        self.assertEqual([(line.record, line.quantity) for line in lines], [(self.other, 1), (self.record, 2)])
        self.assertEqual(lines[1].subtotal, Decimal('60.00'))
        self.assertEqual(cart_services.cart_total(lines), Decimal('108.00'))

    def test_clear(self):
        cart = cart_services.DatabaseCart(self.user)
        cart.add(self.record)

        cart.clear()

        self.assertEqual(cart.lines(), [])
        self.assertEqual(cart.count(), 0)
