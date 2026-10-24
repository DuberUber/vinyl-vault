from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalog.models import Record
from core.utils import redirect_back

from . import services
from .cart import CartError, cart_total, get_cart
from .forms import MAX_QUANTITY, AddToCartForm, CheckoutForm, UpdateQuantityForm
from .models import Order


# Shopping cart

def cart_detail(request):
    lines = get_cart(request).lines()
    return render(request, 'orders/cart_detail.html', {
        'lines': lines,
        'total': cart_total(lines),
        'short_lines': [line for line in lines if line.is_short],
    })


@require_POST
def add_to_cart(request, record_id):
    record = get_object_or_404(Record, pk=record_id)
    form = AddToCartForm(request.POST)
    if not form.is_valid():
        messages.error(request, f'Choose a quantity between 1 and {MAX_QUANTITY}.')
        return redirect(record)
    try:
        get_cart(request).add(record, form.cleaned_data['quantity'])
    except CartError as error:
        messages.error(request, str(error))
        return redirect(record)
    messages.success(request, f'Added "{record.title}" to your cart.')
    return redirect_back(request, 'orders:cart')


@require_POST
def update_item(request, record_id):
    record = get_object_or_404(Record, pk=record_id)
    form = UpdateQuantityForm(request.POST)
    if not form.is_valid():
        messages.error(request, f'Choose a quantity between 0 and {MAX_QUANTITY}.')
        return redirect('orders:cart')
    try:
        get_cart(request).update(record, form.cleaned_data['quantity'])
    except CartError as error:
        messages.error(request, str(error))
    else:
        if form.cleaned_data['quantity'] == 0:
            messages.success(request, f'Removed "{record.title}" from your cart.')
    return redirect('orders:cart')


@require_POST
def remove_item(request, record_id):
    record = get_object_or_404(Record, pk=record_id)
    get_cart(request).remove(record)
    messages.success(request, f'Removed "{record.title}" from your cart.')
    return redirect('orders:cart')


# Checkout and order history

@login_required
def checkout(request):
    lines = get_cart(request).lines()
    if not lines:
        messages.warning(request, 'Your cart is empty, add some records before checking out.')
        return redirect('orders:cart')
    if any(line.is_short for line in lines):
        messages.warning(request, 'Some records in your cart have sold out or run low. Please update your cart.')
        return redirect('orders:cart')

    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            try:
                order = services.place_order(request.user, **form.cleaned_data)
            except services.CheckoutError as error:
                messages.error(request, str(error))
                return redirect('orders:cart')
            messages.success(request, f'Thank you! Order {order.number} has been placed.')
            return redirect(order)
    else:
        user = request.user
        form = CheckoutForm(initial={'full_name': user.get_full_name(), 'email': user.email})

    return render(request, 'orders/checkout.html', {'form': form, 'lines': lines, 'total': cart_total(lines)})


@login_required
def order_list(request):
    orders = Order.objects.filter(user=request.user).prefetch_related('items')
    page = Paginator(orders, 10).get_page(request.GET.get('page'))
    return render(request, 'orders/order_list.html', {'orders': page.object_list, 'page_obj': page})


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related('items'), pk=order_id, user=request.user)
    return render(request, 'orders/order_detail.html', {'order': order})


@login_required
@require_POST
def cancel_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id, user=request.user)
    try:
        services.cancel_order(order, user=request.user, by_customer=True)
    except services.OrderError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f'Order {order.number} has been cancelled.')
    return redirect(order)
