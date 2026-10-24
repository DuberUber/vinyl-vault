import os
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.views import View

from catalog.models import Artist, Genre, PriceChange, Record, StockAdjustment
from orders.cart import DatabaseCart
from orders.models import Order
from staffdash.roles import INVENTORY, SALES
from wishlist.models import WishlistItem

from .mixins import AnyPermissionRequiredMixin
from .templatetags.core_extras import currency, signed, sleeve_hue
from .testing import make_record, make_user


class TemplateFilterTests(SimpleTestCase):
    @override_settings(CURRENCY_SYMBOL='€')
    def test_currency_formats_with_two_decimals_and_thousands_separator(self):
        self.assertEqual(currency(Decimal('1234.5')), '€1,234.50')
        self.assertEqual(currency(9), '€9.00')

    def test_currency_empty_values_render_blank(self):
        self.assertEqual(currency(None), '')
        self.assertEqual(currency(''), '')

    def test_sleeve_hue_is_stable_and_in_range(self):
        self.assertEqual(sleeve_hue('Blue Train'), sleeve_hue('Blue Train'))
        self.assertTrue(all(0 <= sleeve_hue(title) < 360 for title in ['Blue Train', 'Rumours', '', 'Illmatic']))

    def test_signed(self):
        self.assertEqual([signed(3), signed(-2), signed(0), signed(Decimal('-12.50'))], ['+3', '−2', '0', '−12.50'])


class OrdersOrStockView(AnyPermissionRequiredMixin, View):
    permission_required = ('orders.view_order', 'catalog.adjust_stock')

    def get(self, request):
        return HttpResponse('ok')


class AnyPermissionRequiredMixinTests(TestCase):
    def get(self, user):
        request = RequestFactory().get('/staff-only/')
        request.user = user
        return OrdersOrStockView.as_view()(request)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.get(AnonymousUser())

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_user_without_any_of_the_permissions_is_forbidden(self):
        with self.assertRaises(PermissionDenied):
            self.get(make_user('customer'))

    def test_any_one_permission_is_enough(self):
        self.assertEqual(self.get(make_user('stock', INVENTORY)).status_code, 200)
        self.assertEqual(self.get(make_user('sales', SALES)).status_code, 200)


class SiteTests(TestCase):
    def test_health_check(self):
        self.assertEqual(self.client.get(reverse('core:health')).json(), {'status': 'ok'})

    def test_custom_404_page(self):
        response = self.client.get('/no-such-page/')

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, '404.html')

    def test_flash_messages_are_rendered(self):
        record = make_record()

        response = self.client.post(reverse('orders:cart_add', args=[record.pk]), {'quantity': 1}, follow=True)

        self.assertContains(response, 'Added &quot;Blue Train&quot; to your cart.')

    def test_pages_carry_the_shop_name(self):
        self.assertContains(self.client.get(reverse('catalog:home')), '<title>Rare and collectable vinyl · Vinyl Vault</title>', html=True)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SeedDemoDataTests(TestCase):
    def seed(self, *args):
        out = StringIO()
        call_command('seed_demo_data', *args, stdout=out)
        return out.getvalue()

    @staticmethod
    def printed_password(output, username):
        line = next(line for line in output.splitlines() if line.strip().startswith(f'{username} '))
        return line.split()[1]

    def login(self, output, username):
        return authenticate(username=username, password=self.printed_password(output, username))

    def test_seeds_accounts_with_working_printed_passwords_and_roles(self):
        output = self.seed()

        admin, stock, sales = (self.login(output, name) for name in ('admin', 'stock', 'sales'))
        alex, jordan = self.login(output, 'alex'), self.login(output, 'jordan')
        self.assertTrue(admin.is_superuser)
        self.assertEqual(list(stock.groups.values_list('name', flat=True)), [INVENTORY])
        self.assertEqual(list(sales.groups.values_list('name', flat=True)), [SALES])
        self.assertTrue(stock.has_perm('catalog.adjust_stock') and not stock.has_perm('orders.manage_orders'))
        self.assertTrue(sales.has_perm('orders.manage_orders') and not sales.has_perm('catalog.adjust_stock'))
        self.assertFalse(alex.is_staff or jordan.is_staff)

    def test_seeds_a_varied_catalogue(self):
        self.seed()

        self.assertGreaterEqual(Record.objects.count(), 30)
        self.assertEqual(set(Record.objects.values_list('format', flat=True)), set(Record.Format.values))
        self.assertTrue(Record.objects.filter(is_rare=True).exists())
        self.assertTrue(Record.objects.filter(stock=0).exists())
        self.assertTrue(Record.objects.filter(artist__name__icontains='jazz').exists())  # for ?q=jazz
        self.assertEqual(StockAdjustment.objects.filter(reason=StockAdjustment.Reason.INITIAL).count(), Record.objects.count())

    def test_seeds_a_saved_cart_wishlists_and_past_orders(self):
        self.seed()
        User = get_user_model()
        alex, jordan = User.objects.get(username='alex'), User.objects.get(username='jordan')

        lines = DatabaseCart(alex).lines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(any(line.is_short for line in lines))  # shows the stock-dropped warning
        items = WishlistItem.objects.filter(user=jordan).select_related('record')
        self.assertTrue(any(item.price_drop for item in items))
        self.assertTrue(any(item.back_in_stock for item in items))
        self.assertEqual(
            set(Order.objects.values_list('status', flat=True)), set(Order.Status.values)
        )
        self.assertTrue(all(order.items.exists() for order in Order.objects.all()))

    def test_running_twice_is_safe_and_resets_demo_values(self):
        self.seed()
        counts = (Record.objects.count(), Artist.objects.count(), Genre.objects.count(), Order.objects.count(),
                  WishlistItem.objects.count())
        record = Record.objects.get(catalogue_key='BSK3010')
        Record.objects.filter(pk=record.pk).update(stock=0, price=Decimal('1.00'))

        output = self.seed()

        self.assertIn('(0 new)', output)
        self.assertEqual(
            (Record.objects.count(), Artist.objects.count(), Genre.objects.count(), Order.objects.count(),
             WishlistItem.objects.count()),
            counts,
        )
        record.refresh_from_db()
        self.assertEqual((record.stock, record.price), (4, Decimal('38.00')))
        # The reset is logged like any other stock or price change.
        self.assertTrue(StockAdjustment.objects.filter(record=record, note='Demo data reset', change=4).exists())
        self.assertTrue(PriceChange.objects.filter(record=record, note='Demo data reset').exists())

    def test_passwords_change_on_every_run(self):
        first, second = self.seed(), self.seed()

        self.assertNotEqual(self.printed_password(first, 'alex'), self.printed_password(second, 'alex'))
        self.assertIsNone(self.login(first, 'alex'))
        self.assertIsNotNone(self.login(second, 'alex'))

    def test_reset_removes_other_records(self):
        self.seed()
        make_record('Staff pick', catalogue_number='PICK 1')

        self.seed('--reset')

        self.assertFalse(Record.objects.filter(title='Staff pick').exists())
        self.assertGreaterEqual(Record.objects.count(), 30)

    @mock.patch.dict(os.environ, {'DEMO_PASSWORD': 'known-demo-password'})
    def test_password_can_come_from_the_environment(self):
        self.seed()

        self.assertIsNotNone(authenticate(username='jordan', password='known-demo-password'))
