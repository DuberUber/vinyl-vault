from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog import services as inventory
from catalog.models import Grade, Record, StockAdjustment
from core.testing import make_record
from orders import services
from orders.cart import DatabaseCart
from orders.models import Order, OrderItem

SHIPPING = {
    'full_name': 'Alex Byrne',
    'email': 'alex@example.com',
    'shipping_address': '1 Groove Street\nDublin 8',
}


class OrdersTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.rumours = make_record(
            'Rumours', 'Fleetwood Mac', 'Rock', label='Warner Bros.', catalogue_number='BSK 3010',
            media_grade=Grade.NEAR_MINT, sleeve_grade=Grade.VERY_GOOD_PLUS, price=Decimal('38.00'), stock=2,
        )
        cls.blue_monday = make_record(
            'Blue Monday', 'New Order', 'Electronic', label='Factory', catalogue_number='FAC 73',
            format=Record.Format.TWELVE_INCH, price=Decimal('35.00'), stock=5,
        )
        cls.user = User.objects.create_user('alex', email='alex@example.com', first_name='Alex', last_name='Byrne')
        cls.rival = User.objects.create_user('jordan')
        cls.superuser = User.objects.create_superuser('admin', 'admin@example.com', 'unused')

    def setUp(self):
        self.client.force_login(self.user)
        self.cart = DatabaseCart(self.user)

    def fill_cart(self):
        self.cart.add(self.rumours, 2)
        self.cart.add(self.blue_monday, 1)

    def stock(self):
        return tuple(Record.objects.filter(pk__in=[self.rumours.pk, self.blue_monday.pk]).order_by('pk')
                     .values_list('stock', flat=True))

    def place_order(self):
        self.fill_cart()
        return services.place_order(self.user, **SHIPPING)


@override_settings(CURRENCY_SYMBOL='€')
class CheckoutViewTests(OrdersTestCase):
    def test_empty_cart_redirects_back(self):
        self.assertRedirects(self.client.get(reverse('orders:checkout')), reverse('orders:cart'))

    def test_checkout_page_prefills_customer_details(self):
        self.fill_cart()

        response = self.client.get(reverse('orders:checkout'))

        self.assertContains(response, 'Rumours')
        self.assertContains(response, '€111.00')  # 2 × 38 + 35
        self.assertEqual(response.context['form'].initial, {'full_name': 'Alex Byrne', 'email': 'alex@example.com'})

    def test_placing_an_order(self):
        self.fill_cart()

        response = self.client.post(reverse('orders:checkout'), SHIPPING, follow=True)

        order = Order.objects.get()
        self.assertRedirects(response, order.get_absolute_url())
        self.assertContains(response, f'Order {order.number} has been placed.')
        self.assertTrue(order.number.startswith('VV-'))
        self.assertEqual((order.status, order.total), (Order.Status.PENDING, Decimal('111.00')))
        self.assertEqual(self.stock(), (0, 4))
        self.assertEqual(self.cart.lines(), [])

    def test_missing_shipping_details_change_nothing(self):
        self.fill_cart()

        response = self.client.post(reverse('orders:checkout'), {**SHIPPING, 'shipping_address': ''})

        self.assertTrue(response.context['form'].has_error('shipping_address'))
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.stock(), (2, 5))

    def test_stock_is_rechecked_when_ordering(self):
        self.fill_cart()
        Record.objects.filter(pk=self.rumours.pk).update(stock=1)  # someone else bought a copy meanwhile

        response = self.client.post(reverse('orders:checkout'), SHIPPING)

        self.assertRedirects(response, reverse('orders:cart'))
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.stock(), (1, 5))  # nothing partially decremented
        self.assertEqual(len(self.cart.lines()), 2)

    def test_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse('orders:checkout'))

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('orders:checkout')}")


class CheckoutTransactionTests(OrdersTestCase):
    def test_last_copy_goes_to_whoever_checks_out_first(self):
        self.cart.add(self.rumours, 2)
        rival_cart = DatabaseCart(self.rival)
        rival_cart.add(self.rumours, 1)
        rival_cart.add(self.blue_monday, 2)

        services.place_order(self.user, **SHIPPING)
        with self.assertRaisesMessage(services.CheckoutError, '"Rumours" has 0 left and your cart has 1.'):
            services.place_order(self.rival, **SHIPPING)

        self.assertEqual(Order.objects.filter(user=self.rival).count(), 0)
        self.assertEqual(self.stock(), (0, 5))  # the rival's Blue Monday wasn't taken either
        self.assertEqual(len(rival_cart.lines()), 2)

    def test_stock_is_read_after_the_rows_are_locked(self):
        """A rival checkout that commits just before ours gets the lock must be seen, not overwritten."""
        self.fill_cart()
        DatabaseCart(self.rival).add(self.rumours, 1)
        real_lock = services.lock_records
        rival_done = []

        def rival_checks_out_first(record_ids):
            if not rival_done:
                rival_done.append(True)
                services.place_order(self.rival, **SHIPPING)
            return real_lock(record_ids)

        with mock.patch.object(services, 'lock_records', side_effect=rival_checks_out_first):
            # Our cart was valid when it was read, but the stock check sees the rival's sale.
            with self.assertRaisesMessage(services.CheckoutError, '"Rumours" has 1 left and your cart has 2.'):
                services.place_order(self.user, **SHIPPING)

        # (The simulated rival ran inside our transaction, so its order was rolled back with ours.)
        self.assertFalse(Order.objects.filter(user=self.user).exists())
        self.assertEqual(len(self.cart.lines()), 2)

    def test_checkout_locks_the_records_with_select_for_update(self):
        self.fill_cart()
        real_select_for_update = QuerySet.select_for_update

        with mock.patch.object(QuerySet, 'select_for_update', autospec=True,
                               side_effect=real_select_for_update) as select_for_update:
            services.place_order(self.user, **SHIPPING)

        locked_models = {call.args[0].model for call in select_for_update.call_args_list}
        self.assertIn(Record, locked_models)

    def test_a_failure_part_way_through_rolls_everything_back(self):
        self.fill_cart()
        real_apply = inventory.apply_stock_change
        calls = []

        def fail_on_second_line(record, change, **kwargs):
            calls.append(record)
            if len(calls) == 2:
                raise RuntimeError('disk full')
            return real_apply(record, change, **kwargs)

        with mock.patch.object(services, 'apply_stock_change', side_effect=fail_on_second_line):
            with self.assertRaises(RuntimeError):
                services.place_order(self.user, **SHIPPING)

        self.assertFalse(Order.objects.exists())
        self.assertFalse(OrderItem.objects.exists())
        self.assertFalse(StockAdjustment.objects.exists())
        self.assertEqual(self.stock(), (2, 5))
        self.assertEqual(len(self.cart.lines()), 2)

    def test_empty_cart_cannot_be_ordered(self):
        with self.assertRaisesMessage(services.CheckoutError, 'Your cart is empty.'):
            services.place_order(self.user, **SHIPPING)

    def test_sales_are_logged_as_stock_adjustments(self):
        order = self.place_order()

        log = StockAdjustment.objects.filter(reason=StockAdjustment.Reason.SALE).order_by('record_id')
        self.assertEqual(
            list(log.values_list('record__title', 'change', 'stock_after', 'note', 'user__username')),
            [('Rumours', -2, 0, order.number, 'alex'), ('Blue Monday', -1, 4, order.number, 'alex')],
        )


class OrderSnapshotTests(OrdersTestCase):
    def test_items_snapshot_title_artist_format_condition_and_price(self):
        order = self.place_order()

        self.assertEqual(
            list(order.items.values_list('title', 'artist', 'format', 'condition', 'unit_price', 'quantity')),
            [
                ('Rumours', 'Fleetwood Mac', 'LP', 'NM / VG+', Decimal('38.00'), 2),
                ('Blue Monday', 'New Order', '12" single', 'VG+ / VG+', Decimal('35.00'), 1),
            ],
        )

    def test_snapshots_survive_catalogue_edits_and_deletion(self):
        order = self.place_order()
        Record.objects.filter(pk=self.rumours.pk).update(
            title='Rumours (Remastered)', price=Decimal('99.00'), media_grade=Grade.GOOD, format=Record.Format.BOX_SET,
        )
        self.blue_monday.delete()

        rows = list(order.items.values_list('title', 'format', 'condition', 'unit_price', 'record'))

        self.assertEqual(rows, [
            ('Rumours', 'LP', 'NM / VG+', Decimal('38.00'), self.rumours.pk),
            ('Blue Monday', '12" single', 'VG+ / VG+', Decimal('35.00'), None),
        ])
        self.assertEqual(order.total, Decimal('111.00'))
        page = self.client.get(order.get_absolute_url())
        self.assertContains(page, 'Blue Monday')
        self.assertContains(page, 'NM / VG+')


class OrderHistoryTests(OrdersTestCase):
    def test_order_list_shows_only_my_orders(self):
        mine = self.place_order()
        DatabaseCart(self.rival).add(self.blue_monday)
        theirs = services.place_order(self.rival, **SHIPPING)

        response = self.client.get(reverse('orders:list'))

        self.assertEqual(list(response.context['orders']), [mine])
        self.assertNotContains(response, theirs.number)

    def test_cannot_view_someone_elses_order(self):
        order = self.place_order()
        self.client.force_login(self.rival)

        self.assertEqual(self.client.get(order.get_absolute_url()).status_code, 404)


class OrderStatusTests(OrdersTestCase):
    def test_pending_to_paid_to_shipped(self):
        order = self.place_order()

        services.mark_paid(order)
        services.mark_shipped(order)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.SHIPPED)
        self.assertIsNotNone(order.paid_at)
        self.assertIsNotNone(order.shipped_at)

    def test_orders_must_be_paid_before_shipping(self):
        order = self.place_order()

        with self.assertRaisesMessage(services.OrderError, 'is pending payment, so it can\'t be marked as shipped'):
            services.mark_shipped(order)

    def test_cannot_pay_twice(self):
        order = self.place_order()
        services.mark_paid(order)

        with self.assertRaises(services.OrderError):
            services.mark_paid(order)

    def test_cancelling_restocks_and_logs(self):
        order = self.place_order()
        services.mark_paid(order)

        services.cancel_order(order, user=self.superuser)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertIsNotNone(order.cancelled_at)
        self.assertEqual(self.stock(), (2, 5))
        restocks = StockAdjustment.objects.filter(reason=StockAdjustment.Reason.RESTOCK)
        self.assertEqual(sorted(restocks.values_list('change', flat=True)), [1, 2])
        self.assertEqual(set(restocks.values_list('note', flat=True)), {order.number})

    def test_cancelling_skips_records_that_were_deleted(self):
        order = self.place_order()
        self.blue_monday.delete()

        services.cancel_order(order)

        self.assertEqual(Record.objects.get(pk=self.rumours.pk).stock, 2)

    def test_shipped_and_cancelled_orders_cannot_be_cancelled(self):
        order = self.place_order()
        services.mark_paid(order)
        services.mark_shipped(order)

        with self.assertRaises(services.OrderError):
            services.cancel_order(order)
        self.assertEqual(self.stock(), (0, 4))


class CustomerCancelTests(OrdersTestCase):
    def test_customer_can_cancel_a_pending_order(self):
        order = self.place_order()

        self.client.post(reverse('orders:cancel', args=[order.pk]))

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(self.stock(), (2, 5))

    def test_customer_cannot_cancel_once_paid(self):
        order = self.place_order()
        services.mark_paid(order)

        response = self.client.post(reverse('orders:cancel', args=[order.pk]), follow=True)

        self.assertContains(response, 'is paid, so it can&#x27;t be cancelled')
        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.Status.PAID)
        self.assertEqual(self.stock(), (0, 4))

    def test_cancel_requires_post_and_ownership(self):
        order = self.place_order()

        self.assertEqual(self.client.get(reverse('orders:cancel', args=[order.pk])).status_code, 405)
        self.client.force_login(self.rival)
        self.assertEqual(self.client.post(reverse('orders:cancel', args=[order.pk])).status_code, 404)


class OrderAdminTests(OrdersTestCase):
    def setUp(self):
        super().setUp()
        self.order = self.place_order()
        self.client.force_login(self.superuser)
        self.changelist = reverse('admin:orders_order_changelist')

    def run_action(self, action):
        return self.client.post(self.changelist, {'action': action, '_selected_action': [self.order.pk]})

    def status(self):
        return Order.objects.get(pk=self.order.pk).status

    def test_mark_paid_then_shipped_actions(self):
        self.run_action('mark_paid')
        self.assertEqual(self.status(), Order.Status.PAID)

        self.run_action('mark_shipped')
        self.assertEqual(self.status(), Order.Status.SHIPPED)

    def test_cancel_and_restock_action(self):
        self.run_action('cancel_and_restock')

        self.assertEqual(self.status(), Order.Status.CANCELLED)
        self.assertEqual(self.stock(), (2, 5))

    def test_orders_cannot_be_added_in_admin(self):
        self.assertEqual(self.client.get(reverse('admin:orders_order_add')).status_code, 403)

    def test_order_items_are_shown_read_only(self):
        response = self.client.get(reverse('admin:orders_order_change', args=[self.order.pk]))

        self.assertContains(response, 'Fleetwood Mac')
        self.assertEqual(OrderItem.objects.count(), 2)
