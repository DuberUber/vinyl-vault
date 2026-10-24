"""Checkout and order status changes. Views, the staff dashboard and the admin all go through here."""
from django.db import transaction
from django.db.models import prefetch_related_objects
from django.utils import timezone

from catalog.models import StockAdjustment
from catalog.services import apply_stock_change, lock_records

from .cart import DatabaseCart
from .models import Order, OrderItem


class OrderError(Exception):
    """An order can't be placed or changed, e.g. it has already shipped."""


class CheckoutError(OrderError):
    """The cart can't be turned into an order, e.g. it's empty or stock ran out."""


def snapshot_item(record, quantity, order=None):
    """An order line that copies the record's details as they are now, so later edits don't change it."""
    return OrderItem(
        order=order,
        record=record,
        title=record.title,
        artist=record.artist.name,
        format=record.get_format_display(),
        condition=record.condition,
        unit_price=record.price,
        quantity=quantity,
    )


@transaction.atomic
def place_order(user, *, full_name, email, shipping_address):
    """Turn the user's saved cart into a pending order.

    Every record in the cart is locked and re-checked before anything is written, so either the
    whole order goes through (stock decremented, items snapshotted, cart emptied) or nothing changes.
    """
    cart = DatabaseCart(user)
    quantities = cart.quantities()
    if not quantities:
        raise CheckoutError('Your cart is empty.')

    # Read stock only after taking the lock, so a sale that committed a moment ago is seen.
    records = lock_records(list(quantities))
    problems = []
    for pk, quantity in quantities.items():
        record = records.get(pk)
        if record is None:
            problems.append('A record in your cart is no longer for sale.')
        elif record.stock < quantity:
            problems.append(f'"{record.title}" has {record.stock} left and your cart has {quantity}.')
    if problems:
        raise CheckoutError(' '.join(['Sorry, stock changed while you were shopping.', *problems]))

    prefetch_related_objects(list(records.values()), 'artist')
    lines = [(records[pk], quantity) for pk, quantity in quantities.items()]
    order = Order.objects.create(
        user=user,
        full_name=full_name,
        email=email,
        shipping_address=shipping_address,
        total=sum(record.price * quantity for record, quantity in lines),
    )
    OrderItem.objects.bulk_create([snapshot_item(record, quantity, order) for record, quantity in lines])
    for record, quantity in lines:
        apply_stock_change(record, -quantity, reason=StockAdjustment.Reason.SALE, user=user, note=order.number)
    cart.clear()
    return order


def _lock_order(order):
    return Order.objects.select_for_update().get(pk=order.pk)


def _status_error(order, action):
    return OrderError(f'Order {order.number} is {order.get_status_display().lower()}, so it can\'t be {action}.')


@transaction.atomic
def mark_paid(order):
    order = _lock_order(order)
    if not order.can_mark_paid:
        raise _status_error(order, 'marked as paid')
    order.status, order.paid_at = Order.Status.PAID, timezone.now()
    order.save(update_fields=['status', 'paid_at', 'updated_at'])
    return order


@transaction.atomic
def mark_shipped(order):
    order = _lock_order(order)
    if not order.can_mark_shipped:
        raise _status_error(order, 'marked as shipped')
    order.status, order.shipped_at = Order.Status.SHIPPED, timezone.now()
    order.save(update_fields=['status', 'shipped_at', 'updated_at'])
    return order


@transaction.atomic
def cancel_order(order, *, user=None, by_customer=False):
    """Cancel an order and put its records back in stock (logged as stock adjustments).

    Customers can cancel pending orders; staff can also cancel paid ones. Shipped orders can't be cancelled.
    """
    order = _lock_order(order)
    if not (order.customer_can_cancel if by_customer else order.can_cancel):
        raise _status_error(order, 'cancelled')
    items = list(order.items.exclude(record=None))
    records = lock_records([item.record_id for item in items])
    for item in items:
        if item.record_id in records:
            apply_stock_change(
                records[item.record_id], item.quantity,
                reason=StockAdjustment.Reason.RESTOCK, user=user, note=order.number,
            )
    order.status, order.cancelled_at = Order.Status.CANCELLED, timezone.now()
    order.save(update_fields=['status', 'cancelled_at', 'updated_at'])
    return order
