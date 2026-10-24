from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import Record
from core.testing import make_record
from orders.cart import DatabaseCart

from . import services
from .models import WishlistItem


@override_settings(CURRENCY_SYMBOL='€')
class WishlistTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pink_moon = make_record('Pink Moon', 'Nick Drake', 'Folk', price=Decimal('350.00'), stock=1)
        cls.kind_of_blue = make_record('Kind of Blue', 'Miles Davis', 'Jazz', price=Decimal('280.00'), stock=0)
        cls.user = get_user_model().objects.create_user('jordan')

    def setUp(self):
        self.client.force_login(self.user)

    def toggle(self, record, json=False, **data):
        headers = {'Accept': 'application/json'} if json else {}
        return self.client.post(reverse('wishlist:toggle', args=[record.pk]), data, headers=headers)

    def saved(self):
        return list(WishlistItem.objects.filter(user=self.user).values_list('record__title', flat=True))


class ToggleTests(WishlistTestCase):
    def test_heart_saves_then_unsaves(self):
        response = self.toggle(self.pink_moon)

        self.assertRedirects(response, self.pink_moon.get_absolute_url())
        item = WishlistItem.objects.get()
        self.assertEqual((item.record, item.price_when_added, item.in_stock_when_added),
                         (self.pink_moon, Decimal('350.00'), True))

        self.toggle(self.pink_moon)
        self.assertEqual(self.saved(), [])

    def test_sold_out_records_remember_they_were_out_of_stock(self):
        self.toggle(self.kind_of_blue)

        self.assertFalse(WishlistItem.objects.get().in_stock_when_added)

    def test_json_toggle_for_the_in_page_heart(self):
        response = self.toggle(self.pink_moon, json=True)

        self.assertEqual(response.json(), {'saved': True, 'count': 1, 'news': 0})
        self.assertEqual(self.toggle(self.pink_moon, json=True).json()['saved'], False)

    def test_returns_to_the_page_it_came_from(self):
        response = self.toggle(self.pink_moon, next='/records/?genre=1')

        self.assertRedirects(response, '/records/?genre=1', fetch_redirect_response=False)

    def test_guests_are_sent_to_log_in(self):
        self.client.logout()

        response = self.toggle(self.pink_moon)
        json_response = self.toggle(self.pink_moon, json=True)

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={self.pink_moon.get_absolute_url()}")
        self.assertEqual(json_response.status_code, 401)
        self.assertIn('login_url', json_response.json())
        self.assertFalse(WishlistItem.objects.exists())

    def test_requires_post(self):
        self.assertEqual(self.client.get(reverse('wishlist:toggle', args=[self.pink_moon.pk])).status_code, 405)

    def test_heart_shows_saved_state_on_the_record_page(self):
        self.assertContains(self.client.get(self.pink_moon.get_absolute_url()), 'aria-pressed="false"')

        services.add(self.user, self.pink_moon)

        self.assertContains(self.client.get(self.pink_moon.get_absolute_url()), 'aria-pressed="true"')

    def test_one_entry_per_record(self):
        services.add(self.user, self.pink_moon)
        services.add(self.user, self.pink_moon)

        self.assertEqual(WishlistItem.objects.count(), 1)
        with self.assertRaises(IntegrityError):
            WishlistItem.objects.create(user=self.user, record=self.pink_moon, price_when_added=1)


class WishlistPageTests(WishlistTestCase):
    def test_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse('wishlist:detail'))

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('wishlist:detail')}")

    def test_lists_only_my_saved_records(self):
        services.add(self.user, self.pink_moon)
        services.add(get_user_model().objects.create_user('alex'), self.kind_of_blue)

        response = self.client.get(reverse('wishlist:detail'))

        self.assertEqual([item.record for item in response.context['items']], [self.pink_moon])

    def test_price_drop_badge(self):
        services.add(self.user, self.pink_moon)
        Record.objects.filter(pk=self.pink_moon.pk).update(price=Decimal('300.00'))

        response = self.client.get(reverse('wishlist:detail'))

        self.assertContains(response, 'Price dropped €50.00')
        self.assertContains(response, '<span class="price-was ms-1">€350.00</span>', html=True)

    def test_price_rise_shows_no_badge(self):
        services.add(self.user, self.pink_moon)
        Record.objects.filter(pk=self.pink_moon.pk).update(price=Decimal('400.00'))

        item = WishlistItem.objects.select_related('record').get()

        self.assertEqual(item.price_drop, 0)
        self.assertFalse(item.has_news)
        self.assertNotContains(self.client.get(reverse('wishlist:detail')), 'Price dropped')

    def test_back_in_stock_badge(self):
        services.add(self.user, self.kind_of_blue)
        self.assertNotContains(self.client.get(reverse('wishlist:detail')), 'Back in stock')

        Record.objects.filter(pk=self.kind_of_blue.pk).update(stock=2)

        self.assertContains(self.client.get(reverse('wishlist:detail')), 'Back in stock')

    def test_nav_badge_counts_saved_records_and_flags_news(self):
        services.add(self.user, self.pink_moon)
        services.add(self.user, self.kind_of_blue)
        Record.objects.filter(pk=self.kind_of_blue.pk).update(stock=1)

        response = self.client.get(reverse('catalog:home'))

        self.assertEqual((response.context['wishlist_count'], response.context['wishlist_news_count']), (2, 1))
        self.assertContains(response, 'class="news-dot"')


class MoveToCartTests(WishlistTestCase):
    def move(self, record):
        return self.client.post(reverse('wishlist:move_to_cart', args=[record.pk]), follow=True)

    def test_moves_the_record_into_the_saved_cart(self):
        services.add(self.user, self.pink_moon)

        response = self.move(self.pink_moon)

        self.assertContains(response, 'Moved &quot;Pink Moon&quot; to your cart.')
        self.assertEqual(DatabaseCart(self.user).quantities(), {self.pink_moon.pk: 1})
        self.assertEqual(self.saved(), [])

    def test_sold_out_records_stay_on_the_wishlist(self):
        services.add(self.user, self.kind_of_blue)

        response = self.move(self.kind_of_blue)

        self.assertContains(response, 'is out of stock')
        self.assertEqual(DatabaseCart(self.user).quantities(), {})
        self.assertEqual(self.saved(), ['Kind of Blue'])

    def test_only_records_on_my_wishlist(self):
        self.assertEqual(self.move(self.pink_moon).status_code, 404)
