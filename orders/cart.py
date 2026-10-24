"""The shopping cart's public interface.

Guests keep their cart in the session; signed-in customers have a saved cart in the database that
follows them across devices. Both sit behind the same interface (``get_cart(request)``), and when a
guest logs in their session cart is merged into their saved cart (``merge_session_cart``).

Adding to the cart checks stock but doesn't reserve it: checkout (orders.services) re-checks under a
row lock. If stock drops below what's in a cart, the cart page warns about that line.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.template.defaultfilters import pluralize

from catalog.models import Record

from .models import Cart, CartItem

SESSION_KEY = 'cart'


class CartError(Exception):
    """A cart change that can't be made, e.g. asking for more copies than are in stock."""


@dataclass(frozen=True)
class CartLine:
    record: Record
    quantity: int

    @property
    def subtotal(self):
        return self.record.price * self.quantity

    @property
    def is_short(self):
        """Stock has dropped below the quantity in the cart since it was added."""
        return self.quantity > self.record.stock


def check_stock(record, quantity):
    if record.stock == 0:
        raise CartError(f'Sorry, "{record.title}" is out of stock.')
    if quantity > record.stock:
        raise CartError(
            f'Sorry, we only have {record.stock} cop{pluralize(record.stock, "y,ies")} of "{record.title}".'
        )


class BaseCart:
    """Shared cart behaviour; subclasses store ``{record_id: quantity}`` somewhere."""

    def quantities(self):
        raise NotImplementedError

    def _store(self, record_id, quantity):
        """Save one line; a quantity of zero removes it."""
        raise NotImplementedError

    def clear(self):
        raise NotImplementedError

    def lines(self):
        """The cart's lines with their current records, in the order they were added."""
        quantities = self.quantities()
        records = Record.objects.select_related('artist', 'genre').in_bulk(list(quantities))
        return [CartLine(records[pk], quantity) for pk, quantity in quantities.items() if pk in records]

    def quantity_of(self, record):
        return self.quantities().get(record.pk, 0)

    def count(self):
        return sum(self.quantities().values())

    def add(self, record, quantity=1):
        new_quantity = self.quantity_of(record) + quantity
        check_stock(record, new_quantity)
        self._store(record.pk, new_quantity)
        return new_quantity

    def update(self, record, quantity):
        """Change a line's quantity; zero removes the line. Lowering a quantity is always allowed."""
        if 0 < quantity and quantity > min(self.quantity_of(record), record.stock):
            check_stock(record, quantity)
        self._store(record.pk, max(quantity, 0))

    def remove(self, record):
        self._store(record.pk, 0)


class SessionCart(BaseCart):
    def __init__(self, session):
        self.session = session

    def quantities(self):
        # Session data is JSON, so keys are strings.
        return {int(pk): quantity for pk, quantity in self.session.get(SESSION_KEY, {}).items()}

    def _store(self, record_id, quantity):
        data = self.session.get(SESSION_KEY, {})
        if quantity:
            data[str(record_id)] = quantity
        else:
            data.pop(str(record_id), None)
        self.session[SESSION_KEY] = data

    def clear(self):
        self.session.pop(SESSION_KEY, None)


class DatabaseCart(BaseCart):
    def __init__(self, user):
        self.user = user

    def quantities(self):
        items = CartItem.objects.filter(cart__user=self.user).order_by('added_at', 'pk')
        return dict(items.values_list('record_id', 'quantity'))

    def _store(self, record_id, quantity):
        cart, _ = Cart.objects.get_or_create(user=self.user)
        if quantity:
            CartItem.objects.update_or_create(cart=cart, record_id=record_id, defaults={'quantity': quantity})
        else:
            CartItem.objects.filter(cart=cart, record_id=record_id).delete()
        cart.save(update_fields=['updated_at'])

    def clear(self):
        CartItem.objects.filter(cart__user=self.user).delete()


def get_cart(request):
    if request.user.is_authenticated:
        return DatabaseCart(request.user)
    return SessionCart(request.session)


def cart_total(lines):
    return sum((line.subtotal for line in lines), Decimal('0.00'))


def merge_session_cart(session, user):
    """Move a guest's session cart into the user's saved cart, adding quantities together.

    Quantities are capped at the stock available. Returns messages describing any lines that
    couldn't be merged in full.
    """
    guest = SessionCart(session)
    guest_quantities = guest.quantities()
    if not guest_quantities:
        return []
    saved = DatabaseCart(user)
    saved_quantities = saved.quantities()
    notes = []
    for pk, record in Record.objects.in_bulk(list(guest_quantities)).items():
        current = saved_quantities.get(pk, 0)
        wanted = current + guest_quantities[pk]
        merged = max(current, min(wanted, record.stock))
        if merged != current:
            saved._store(pk, merged)
        if merged < wanted:
            notes.append(
                f'We only have {record.stock} cop{pluralize(record.stock, "y,ies")} of "{record.title}", '
                f'so your cart has {merged}.'
            )
    guest.clear()
    return notes
