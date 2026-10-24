"""Staff dashboards. Every view checks a Django permission (granted through the Inventory and Sales groups):
anonymous visitors are sent to log in and signed-in users without the permission get a 403.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Avg, Count, F, Sum
from django.db.models.functions import TruncDate
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView

from catalog import services as inventory
from catalog.forms import RecordForm
from catalog.models import PriceChange, Record, StockAdjustment
from catalog.search import text_query
from core.mixins import AnyPermissionRequiredMixin
from orders import services as order_services
from orders.models import Order, OrderItem

from .forms import BulkPriceForm, PriceForm, StockAdjustmentForm
from .roles import DASHBOARD_PERMISSIONS

SALES_WINDOW_DAYS = 30
STAFF_PAGE_SIZE = 25


class DashboardView(AnyPermissionRequiredMixin, TemplateView):
    template_name = 'staffdash/home.html'
    permission_required = DASHBOARD_PERMISSIONS

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            low_stock=Record.objects.filter(stock__lte=settings.LOW_STOCK_THRESHOLD)
            .select_related('artist').order_by('stock', 'title')[:10],
            low_stock_threshold=settings.LOW_STOCK_THRESHOLD,
            recent_orders=Order.objects.select_related('user')[:8],
            most_wishlisted=Record.objects.annotate(wishes=Count('wishlist_items'))
            .filter(wishes__gt=0).select_related('artist').order_by('-wishes', 'title')[:5],
            **sales_summary(SALES_WINDOW_DAYS),
            **kwargs,
        )


def sales_summary(days):
    """Paid and shipped orders over the last ``days`` days, computed with database aggregates."""
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    sales = Order.objects.filter(status__in=Order.SALE_STATUSES, created_at__date__gte=start)
    sold_items = OrderItem.objects.filter(order__in=sales)

    totals = sales.aggregate(revenue=Sum('total'), orders=Count('pk'), average=Avg('total'))
    totals['units'] = sold_items.aggregate(units=Sum('quantity'))['units']
    pending = Order.objects.filter(status=Order.Status.PENDING).aggregate(count=Count('pk'), value=Sum('total'))

    by_day = dict(
        sales.annotate(day=TruncDate('created_at')).values('day').annotate(revenue=Sum('total'))
        .values_list('day', 'revenue')
    )
    best_day = max(by_day.values(), default=0) or 1
    daily = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        revenue = by_day.get(day, 0)
        daily.append({'day': day, 'revenue': revenue, 'percent': round(100 * revenue / best_day)})

    top_sellers = (
        sold_items.values('title', 'artist')
        .annotate(units=Sum('quantity'), revenue=Sum(F('unit_price') * F('quantity')))
        .order_by('-units', '-revenue')[:5]
    )
    return {
        'sales_days': days, 'sales': totals, 'pending': pending, 'daily_sales': daily, 'top_sellers': top_sellers,
    }


# Inventory

class InventoryListView(PermissionRequiredMixin, ListView):
    permission_required = 'catalog.change_record'
    template_name = 'staffdash/inventory_list.html'
    context_object_name = 'records'
    paginate_by = STAFF_PAGE_SIZE

    def get_queryset(self):
        records = Record.objects.select_related('artist', 'genre').order_by('artist__name', 'title', 'pk')
        q = self.request.GET.get('q', '').strip()
        if q:
            records = records.filter(text_query(q))
        if self.request.GET.get('low'):
            records = records.filter(stock__lte=settings.LOW_STOCK_THRESHOLD).order_by('stock', 'title', 'pk')
        return records

    def get_context_data(self, **kwargs):
        return super().get_context_data(low_stock_threshold=settings.LOW_STOCK_THRESHOLD, **kwargs)


class RecordCreateView(PermissionRequiredMixin, SuccessMessageMixin, CreateView):
    permission_required = 'catalog.add_record'
    model = Record
    form_class = RecordForm
    template_name = 'staffdash/record_form.html'
    success_message = 'Added "%(title)s" to the shop.'

    def form_valid(self, form):
        response = super().form_valid(form)
        inventory.log_initial_stock(self.object, user=self.request.user)
        return response

    def get_success_url(self):
        return reverse('staffdash:inventory')


class RecordUpdateView(PermissionRequiredMixin, SuccessMessageMixin, UpdateView):
    permission_required = 'catalog.change_record'
    model = Record
    queryset = Record.objects.select_related('artist')
    form_class = RecordForm
    pk_url_kwarg = 'record_id'
    template_name = 'staffdash/record_form.html'
    success_message = 'Saved "%(title)s".'

    def get_success_url(self):
        return reverse('staffdash:inventory')


class StockAdjustView(PermissionRequiredMixin, FormView):
    permission_required = 'catalog.adjust_stock'
    form_class = StockAdjustmentForm
    template_name = 'staffdash/stock_adjust.html'

    def dispatch(self, request, *args, **kwargs):
        self.record = get_object_or_404(Record.objects.select_related('artist'), pk=kwargs['record_id'])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            record=self.record,
            adjustments=self.record.stock_adjustments.select_related('user')[:15],
            **kwargs,
        )

    def form_valid(self, form):
        try:
            adjustment = inventory.adjust_stock(self.record, user=self.request.user, **form.cleaned_data)
        except inventory.InventoryError as error:
            form.add_error('change', str(error))
            return self.form_invalid(form)
        messages.success(
            self.request, f'Stock of "{self.record.title}" is now {adjustment.stock_after} ({adjustment.change:+d}).'
        )
        return redirect('staffdash:stock_adjust', self.record.pk)


class StockLogView(PermissionRequiredMixin, ListView):
    permission_required = 'catalog.view_stockadjustment'
    template_name = 'staffdash/stock_log.html'
    context_object_name = 'adjustments'
    paginate_by = STAFF_PAGE_SIZE
    queryset = StockAdjustment.objects.select_related('record__artist', 'user')


# Pricing

class PricingView(PermissionRequiredMixin, ListView):
    """Every record's price, with a form (posted back here) for bulk percentage changes."""

    permission_required = 'catalog.change_price'
    template_name = 'staffdash/pricing.html'
    context_object_name = 'records'
    paginate_by = STAFF_PAGE_SIZE

    def get_queryset(self):
        records = Record.objects.select_related('artist', 'genre').order_by('artist__name', 'title', 'pk')
        q = self.request.GET.get('q', '').strip()
        return records.filter(text_query(q)) if q else records

    def get_context_data(self, **kwargs):
        kwargs.setdefault('bulk_form', BulkPriceForm())
        return super().get_context_data(**kwargs)

    def post(self, request, *args, **kwargs):
        form = BulkPriceForm(request.POST)
        if not form.is_valid():
            self.object_list = self.get_queryset()
            return self.render_to_response(self.get_context_data(bulk_form=form), status=400)
        data = form.cleaned_data
        changes = inventory.bulk_change_price(
            percent=data['percent'], genre=data['genre'], format=data['format'], note=data['note'], user=request.user,
        )
        if changes:
            messages.success(request, f'Changed the price of {len(changes)} record(s) by {data["percent"]:+}%.')
        else:
            messages.warning(request, 'No prices changed: nothing matched, or the change rounded to zero.')
        return redirect('staffdash:price_log')


class PriceUpdateView(PermissionRequiredMixin, FormView):
    """Change one record's price (posted from the pricing list, or with its own page on errors)."""

    permission_required = 'catalog.change_price'
    form_class = PriceForm
    template_name = 'staffdash/price_update.html'

    def dispatch(self, request, *args, **kwargs):
        self.record = get_object_or_404(Record.objects.select_related('artist'), pk=kwargs['record_id'])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {'price': self.record.price}

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            record=self.record, changes=self.record.price_changes.select_related('user')[:10], **kwargs
        )

    def form_valid(self, form):
        old_price = self.record.price
        try:
            inventory.set_price(self.record, form.cleaned_data['price'], user=self.request.user,
                                note=form.cleaned_data['note'])
        except inventory.InventoryError as error:
            form.add_error('price', str(error))
            return self.form_invalid(form)
        messages.success(self.request, f'"{self.record.title}": {old_price} → {self.record.price}.')
        return redirect('staffdash:pricing')


class PriceLogView(PermissionRequiredMixin, ListView):
    permission_required = 'catalog.view_pricechange'
    template_name = 'staffdash/price_log.html'
    context_object_name = 'changes'
    paginate_by = STAFF_PAGE_SIZE
    queryset = PriceChange.objects.select_related('record__artist', 'user')


# Orders

class OrderListView(PermissionRequiredMixin, ListView):
    permission_required = 'orders.view_order'
    template_name = 'staffdash/order_list.html'
    context_object_name = 'orders'
    paginate_by = STAFF_PAGE_SIZE

    def get_queryset(self):
        # Explicit ordering: Meta.ordering doesn't apply to the GROUP BY query the annotation creates.
        orders = (
            Order.objects.select_related('user').annotate(units=Sum('items__quantity')).order_by('-created_at', '-pk')
        )
        self.status = self.request.GET.get('status', '')
        if self.status in Order.Status.values:
            orders = orders.filter(status=self.status)
        return orders

    def get_context_data(self, **kwargs):
        return super().get_context_data(statuses=Order.Status.choices, current_status=self.status, **kwargs)


class OrderDetailView(PermissionRequiredMixin, DetailView):
    permission_required = 'orders.view_order'
    template_name = 'staffdash/order_detail.html'
    queryset = Order.objects.select_related('user').prefetch_related('items')
    pk_url_kwarg = 'order_id'


class OrderActionView(PermissionRequiredMixin, View):
    """Mark an order paid or shipped, or cancel it and restock its records."""

    permission_required = 'orders.manage_orders'
    http_method_names = ['post']

    def post(self, request, order_id, action):
        order = get_object_or_404(Order, pk=order_id)
        actions = {
            'paid': (lambda: order_services.mark_paid(order), 'marked as paid'),
            'shipped': (lambda: order_services.mark_shipped(order), 'marked as shipped'),
            'cancel': (lambda: order_services.cancel_order(order, user=request.user), 'cancelled and restocked'),
        }
        if action not in actions:
            raise Http404('Unknown order action.')
        change, done = actions[action]
        try:
            change()
        except order_services.OrderError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f'Order {order.number} {done}.')
        return redirect('staffdash:order_detail', order.pk)
