from django.db import transaction

from orders.cart import DatabaseCart

from .models import WishlistItem


def add(user, record):
    item, _ = WishlistItem.objects.get_or_create(
        user=user, record=record,
        defaults={'price_when_added': record.price, 'in_stock_when_added': record.in_stock},
    )
    return item


def toggle(user, record):
    """Save the record to the user's wishlist, or remove it if it's already there. Returns True if saved."""
    deleted, _ = WishlistItem.objects.filter(user=user, record=record).delete()
    if deleted:
        return False
    add(user, record)
    return True


@transaction.atomic
def move_to_cart(user, record, quantity=1):
    """Add the record to the user's saved cart and take it off their wishlist.

    Raises orders.cart.CartError (and leaves the wishlist alone) if it's out of stock.
    """
    DatabaseCart(user).add(record, quantity)
    WishlistItem.objects.filter(user=user, record=record).delete()


def summary(user):
    """Record ids on the user's wishlist and how many have news (price drop or back in stock), in one query."""
    rows = WishlistItem.objects.filter(user=user).values_list(
        'record_id', 'price_when_added', 'in_stock_when_added', 'record__price', 'record__stock'
    )
    ids, news = set(), 0
    for record_id, price_when_added, in_stock_when_added, price, stock in rows:
        ids.add(record_id)
        news += price < price_when_added or (not in_stock_when_added and stock > 0)
    return ids, news
