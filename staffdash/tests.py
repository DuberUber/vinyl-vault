from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from catalog.models import PriceChange, Record, StockAdjustment
from core.testing import make_record, make_user
from orders import services as order_services
from orders.cart import DatabaseCart
from orders.models import Order
from wishlist import services as wishlist

from .roles import INVENTORY, SALES

SHIPPING = {'full_name': 'Alex Byrne', 'email': 'alex@example.com', 'shipping_address': '1 Groove Street'}


class StaffTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.stock_user = make_user('stock', INVENTORY)
        cls.sales_user = make_user('sales', SALES)
        cls.customer = make_user('alex')
        cls.rumours = make_record('Rumours', 'Fleetwood Mac', 'Rock', price=Decimal('38.00'), stock=4)
        cls.paranoid = make_record('Paranoid', 'Black Sabbath', 'Rock', price=Decimal('260.00'), stock=1)
        cls.blue_monday = make_record(
            'Blue Monday', 'New Order', 'Electronic', format=Record.Format.TWELVE_INCH, price=Decimal('35.00'), stock=0
        )

    def place_order(self, *lines, user=None):
        user = user or self.customer
        cart = DatabaseCart(user)
        for record, quantity in lines:
            cart.add(record, quantity)
        return order_services.place_order(user, **SHIPPING)


class StaffGroupTests(TestCase):
    """The groups come from the staffdash data migration, so they exist in every fresh database."""

    def perms(self, name):
        return set(Group.objects.get(name=name).permissions.values_list('content_type__app_label', 'codename'))

    def test_inventory_group(self):
        perms = self.perms(INVENTORY)

        self.assertLessEqual(
            {('catalog', 'change_record'), ('catalog', 'add_record'), ('catalog', 'adjust_stock'),
             ('catalog', 'view_stockadjustment')},
            perms,
        )
        self.assertNotIn(('catalog', 'change_price'), perms)
        self.assertNotIn(('orders', 'manage_orders'), perms)

    def test_sales_group(self):
        perms = self.perms(SALES)

        self.assertLessEqual(
            {('catalog', 'change_price'), ('catalog', 'view_pricechange'), ('orders', 'view_order'),
             ('orders', 'manage_orders')},
            perms,
        )
        self.assertNotIn(('catalog', 'adjust_stock'), perms)
        self.assertNotIn(('catalog', 'change_record'), perms)


class AccessTests(StaffTestCase):
    """Who can open which staff page: anonymous users log in, everyone else without the permission gets 403."""

    def urls(self):
        record, order = self.rumours.pk, self.place_order((self.rumours, 1)).pk
        return {
            'home': (reverse('staffdash:home'), {'stock', 'sales'}),
            'inventory': (reverse('staffdash:inventory'), {'stock'}),
            'record_add': (reverse('staffdash:record_add'), {'stock'}),
            'record_edit': (reverse('staffdash:record_edit', args=[record]), {'stock'}),
            'stock_adjust': (reverse('staffdash:stock_adjust', args=[record]), {'stock'}),
            'stock_log': (reverse('staffdash:stock_log'), {'stock'}),
            'pricing': (reverse('staffdash:pricing'), {'sales'}),
            'price_update': (reverse('staffdash:price_update', args=[record]), {'sales'}),
            'price_log': (reverse('staffdash:price_log'), {'sales'}),
            'orders': (reverse('staffdash:orders'), {'sales'}),
            'order_detail': (reverse('staffdash:order_detail', args=[order]), {'sales'}),
        }

    def test_permission_matrix(self):
        users = {'stock': self.stock_user, 'sales': self.sales_user, 'alex': self.customer}
        for name, (url, allowed) in self.urls().items():
            for username, user in users.items():
                with self.subTest(page=name, user=username):
                    self.client.force_login(user)
                    expected = 200 if username in allowed else 403
                    self.assertEqual(self.client.get(url).status_code, expected)

    def test_403_page_is_rendered(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse('staffdash:home'))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')

    def test_anonymous_users_are_sent_to_log_in(self):
        url = reverse('staffdash:inventory')

        self.assertRedirects(self.client.get(url), f"{reverse('accounts:login')}?next={url}")

    def test_is_staff_alone_is_not_enough(self):
        self.client.force_login(make_user('intern', is_staff=True))

        self.assertEqual(self.client.get(reverse('staffdash:home')).status_code, 403)

    def test_superuser_can_open_everything(self):
        self.client.force_login(make_user('boss', is_superuser=True))

        for name, (url, _) in self.urls().items():
            with self.subTest(page=name):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_actions_are_protected_too(self):
        order = self.place_order((self.rumours, 1))
        self.client.force_login(self.stock_user)

        posts = [
            reverse('staffdash:order_action', args=[order.pk, 'paid']),
            reverse('staffdash:price_update', args=[self.rumours.pk]),
            reverse('staffdash:pricing'),
        ]
        for url in posts:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, {'price': '1.00', 'percent': '10'}).status_code, 403)
        self.client.force_login(self.sales_user)
        response = self.client.post(reverse('staffdash:stock_adjust', args=[self.rumours.pk]), {'change': 5, 'reason': 'received'})
        self.assertEqual(response.status_code, 403)

        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.Status.PENDING)
        self.assertEqual(Record.objects.get(pk=self.rumours.pk).stock, 3)
        self.assertFalse(PriceChange.objects.exists())

    def test_nav_shows_the_staff_link_only_to_staff(self):
        self.client.force_login(self.customer)
        self.assertNotContains(self.client.get(reverse('catalog:home')), reverse('staffdash:home'))

        self.client.force_login(self.sales_user)
        self.assertContains(self.client.get(reverse('catalog:home')), reverse('staffdash:home'))

    def test_section_menu_only_lists_permitted_sections(self):
        self.client.force_login(self.sales_user)

        response = self.client.get(reverse('staffdash:home'))

        self.assertContains(response, reverse('staffdash:pricing'))
        self.assertNotContains(response, f'href="{reverse("staffdash:inventory")}"')


@override_settings(LOW_STOCK_THRESHOLD=1)
class DashboardHomeTests(StaffTestCase):
    def setUp(self):
        self.client.force_login(self.sales_user)

    def test_low_stock_most_wishlisted_and_recent_orders(self):
        jordan = make_user('jordan')
        for user in (self.customer, jordan):
            wishlist.add(user, self.blue_monday)
        wishlist.add(jordan, self.paranoid)
        order = self.place_order((self.rumours, 1))

        context = self.client.get(reverse('staffdash:home')).context

        self.assertEqual(list(context['low_stock']), [self.blue_monday, self.paranoid])
        self.assertEqual([(r, r.wishes) for r in context['most_wishlisted']], [(self.blue_monday, 2), (self.paranoid, 1)])
        self.assertEqual(list(context['recent_orders']), [order])

    def test_30_day_sales_count_only_paid_and_shipped_orders_in_the_window(self):
        paid = self.place_order((self.rumours, 2))
        order_services.mark_paid(paid)
        shipped = self.place_order((self.paranoid, 1))
        order_services.mark_paid(shipped)
        order_services.mark_shipped(shipped)
        self.place_order((self.rumours, 1))  # pending: not a sale yet
        cancelled = self.place_order((self.rumours, 1))
        order_services.cancel_order(cancelled)
        old = self.place_order((self.rumours, 1))
        order_services.mark_paid(old)
        Order.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=31))

        context = self.client.get(reverse('staffdash:home')).context

        self.assertEqual(context['sales']['revenue'], Decimal('336.00'))  # 2 × 38 + 260
        self.assertEqual(context['sales']['orders'], 2)
        self.assertEqual(context['sales']['units'], 3)
        self.assertEqual(context['sales']['average'], Decimal('168.00'))
        self.assertEqual((context['pending']['count'], context['pending']['value']), (1, Decimal('38.00')))
        self.assertEqual(len(context['daily_sales']), 30)
        self.assertEqual(context['daily_sales'][-1]['revenue'], Decimal('336.00'))
        self.assertEqual(context['daily_sales'][-1]['percent'], 100)
        self.assertEqual(
            [(s['title'], s['units']) for s in context['top_sellers']], [('Rumours', 2), ('Paranoid', 1)]
        )

    def test_empty_shop(self):
        response = self.client.get(reverse('staffdash:home'))

        self.assertEqual(response.context['sales']['orders'], 0)
        self.assertContains(response, 'No sales in this period.')


class InventoryTests(StaffTestCase):
    def setUp(self):
        self.client.force_login(self.stock_user)

    def record_data(self, **overrides):
        return {
            'title': 'Pink Moon', 'artist_name': 'Nick Drake', 'genre': self.rumours.genre_id, 'label': 'Island',
            'catalogue_number': 'ilps 9184', 'format': 'LP', 'release_year': 1972, 'media_grade': 'VG+',
            'sleeve_grade': 'VG', 'pressing_notes': 'Pink-rim labels.', 'is_rare': 'on', 'price': '350.00',
            'stock': 2, **overrides,
        }

    def test_add_a_record_logs_its_opening_stock(self):
        response = self.client.post(reverse('staffdash:record_add'), self.record_data())

        self.assertRedirects(response, reverse('staffdash:inventory'))
        record = Record.objects.get(title='Pink Moon')
        self.assertEqual((record.artist.name, record.catalogue_number, record.stock), ('Nick Drake', 'ILPS 9184', 2))
        log = StockAdjustment.objects.get(record=record)
        self.assertEqual((log.change, log.reason, log.user), (2, StockAdjustment.Reason.INITIAL, self.stock_user))

    def test_duplicate_pressing_is_reported_on_the_form(self):
        self.client.post(reverse('staffdash:record_add'), self.record_data())

        response = self.client.post(reverse('staffdash:record_add'), self.record_data(catalogue_number='ILPS-9184'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].has_error('catalogue_number'))
        self.assertEqual(Record.objects.filter(title='Pink Moon').count(), 1)

    def test_editing_details_cannot_touch_price_or_stock(self):
        url = reverse('staffdash:record_edit', args=[self.rumours.pk])
        form = self.client.get(url).context['form']
        self.assertNotIn('price', form.fields)
        self.assertNotIn('stock', form.fields)

        self.client.post(url, self.record_data(title='Rumours', artist_name='Fleetwood Mac', price='1.00', stock=99))

        self.rumours.refresh_from_db()
        self.assertEqual((self.rumours.label, self.rumours.price, self.rumours.stock), ('Island', Decimal('38.00'), 4))

    def test_stock_adjustment_is_applied_and_logged(self):
        url = reverse('staffdash:stock_adjust', args=[self.rumours.pk])

        response = self.client.post(url, {'change': 6, 'reason': 'received', 'note': 'Box from the wholesaler'}, follow=True)

        self.assertContains(response, 'Stock of &quot;Rumours&quot; is now 10 (+6).')
        self.assertEqual(Record.objects.get(pk=self.rumours.pk).stock, 10)
        log = StockAdjustment.objects.get()
        self.assertEqual(
            (log.change, log.stock_after, log.reason, log.note, log.user),
            (6, 10, 'received', 'Box from the wholesaler', self.stock_user),
        )
        self.assertContains(self.client.get(reverse('staffdash:stock_log')), 'Box from the wholesaler')

    def test_stock_cannot_go_below_zero(self):
        response = self.client.post(reverse('staffdash:stock_adjust', args=[self.paranoid.pk]), {'change': -2, 'reason': 'damaged'})

        self.assertContains(response, 'only has 1 in stock')
        self.assertEqual(Record.objects.get(pk=self.paranoid.pk).stock, 1)
        self.assertFalse(StockAdjustment.objects.exists())

    def test_zero_and_automatic_reasons_are_rejected(self):
        url = reverse('staffdash:stock_adjust', args=[self.rumours.pk])

        zero = self.client.post(url, {'change': 0, 'reason': 'received'})
        sale = self.client.post(url, {'change': -1, 'reason': 'sale'})

        self.assertTrue(zero.context['form'].has_error('change'))
        self.assertTrue(sale.context['form'].has_error('reason'))
        self.assertFalse(StockAdjustment.objects.exists())

    def test_inventory_list_search_and_low_stock_filter(self):
        with self.settings(LOW_STOCK_THRESHOLD=1):
            low = self.client.get(reverse('staffdash:inventory'), {'low': '1'})
        search = self.client.get(reverse('staffdash:inventory'), {'q': 'sabbath'})

        self.assertEqual(list(low.context['records']), [self.blue_monday, self.paranoid])
        self.assertEqual(list(search.context['records']), [self.paranoid])


class PricingTests(StaffTestCase):
    def setUp(self):
        self.client.force_login(self.sales_user)

    def prices(self):
        return dict(Record.objects.values_list('title', 'price'))

    def test_single_price_change_is_logged(self):
        response = self.client.post(
            reverse('staffdash:price_update', args=[self.rumours.pk]), {'price': '32.50', 'note': 'Summer sale'}
        )

        self.assertRedirects(response, reverse('staffdash:pricing'))
        self.assertEqual(self.prices()['Rumours'], Decimal('32.50'))
        change = PriceChange.objects.get()
        self.assertEqual(
            (change.old_price, change.new_price, change.percent, change.note, change.user),
            (Decimal('38.00'), Decimal('32.50'), None, 'Summer sale', self.sales_user),
        )

    def test_unchanged_price_is_rejected(self):
        response = self.client.post(reverse('staffdash:price_update', args=[self.rumours.pk]), {'price': '38.00'})

        self.assertContains(response, 'already costs 38.00')
        self.assertFalse(PriceChange.objects.exists())

    def test_bulk_change_by_genre(self):
        response = self.client.post(reverse('staffdash:pricing'), {'genre': self.rumours.genre_id, 'percent': '-10'})

        self.assertRedirects(response, reverse('staffdash:price_log'))
        self.assertEqual(self.prices(), {
            'Rumours': Decimal('34.20'), 'Paranoid': Decimal('234.00'), 'Blue Monday': Decimal('35.00'),
        })
        changes = PriceChange.objects.all()
        self.assertEqual(changes.count(), 2)
        self.assertEqual(len(set(changes.values_list('batch', flat=True))), 1)
        self.assertEqual(set(changes.values_list('percent', flat=True)), {Decimal('-10')})

    def test_bulk_change_by_format_and_genre_together(self):
        make_record('Blue Monday 88', 'New Order', 'Rock', format=Record.Format.TWELVE_INCH, price=Decimal('10.00'))

        self.client.post(reverse('staffdash:pricing'), {
            'genre': self.rumours.genre_id, 'format': Record.Format.TWELVE_INCH, 'percent': '12.5',
        })

        self.assertEqual(self.prices()['Blue Monday 88'], Decimal('11.25'))
        self.assertEqual(self.prices()['Rumours'], Decimal('38.00'))
        self.assertEqual(self.prices()['Blue Monday'], Decimal('35.00'))

    def test_bulk_change_needs_a_genre_or_format_and_a_sensible_percentage(self):
        for data in [{'percent': '10'}, {'format': 'LP', 'percent': '0'}, {'format': 'LP', 'percent': '-95'}]:
            with self.subTest(data=data):
                response = self.client.post(reverse('staffdash:pricing'), data)
                self.assertEqual(response.status_code, 400)
        self.assertFalse(PriceChange.objects.exists())
        self.assertEqual(self.prices()['Rumours'], Decimal('38.00'))

    def test_price_log_lists_changes(self):
        self.client.post(reverse('staffdash:price_update', args=[self.paranoid.pk]), {'price': '240', 'note': 'Matched market'})

        self.assertContains(self.client.get(reverse('staffdash:price_log')), 'Matched market')


class OrderManagementTests(StaffTestCase):
    def setUp(self):
        self.client.force_login(self.sales_user)
        self.order = self.place_order((self.rumours, 2), (self.paranoid, 1))

    def act(self, action):
        return self.client.post(reverse('staffdash:order_action', args=[self.order.pk, action]), follow=True)

    def status(self):
        return Order.objects.get(pk=self.order.pk).status

    def test_mark_paid_then_shipped(self):
        self.assertContains(self.act('paid'), f'Order {self.order.number} marked as paid.')
        self.assertEqual(self.status(), Order.Status.PAID)

        self.act('shipped')
        self.assertEqual(self.status(), Order.Status.SHIPPED)

    def test_invalid_transition_shows_an_error(self):
        response = self.act('shipped')

        self.assertContains(response, 'is pending payment, so it can&#x27;t be marked as shipped.')
        self.assertEqual(self.status(), Order.Status.PENDING)

    def test_cancel_paid_order_restocks_and_logs_who_did_it(self):
        self.act('paid')

        self.act('cancel')

        self.assertEqual(self.status(), Order.Status.CANCELLED)
        self.assertEqual(Record.objects.get(pk=self.rumours.pk).stock, 4)
        self.assertEqual(Record.objects.get(pk=self.paranoid.pk).stock, 1)
        restocks = StockAdjustment.objects.filter(reason=StockAdjustment.Reason.RESTOCK)
        self.assertEqual(set(restocks.values_list('user__username', flat=True)), {'sales'})

    def test_unknown_action_is_404(self):
        self.assertEqual(self.act('refund').status_code, 404)

    def test_order_list_filters_by_status(self):
        other = self.place_order((self.rumours, 1))
        order_services.mark_paid(other)

        response = self.client.get(reverse('staffdash:orders'), {'status': 'paid'})

        self.assertEqual(list(response.context['orders']), [other])
        self.assertEqual(response.context['orders'][0].units, 1)
