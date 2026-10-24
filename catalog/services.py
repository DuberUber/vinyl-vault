"""Stock and price changes. Every change goes through here so it is row-locked and logged.

Views, the staff dashboard and checkout (orders.services) call these functions instead of updating
``Record.stock`` or ``Record.price`` directly.
"""
import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from .models import PriceChange, Record, StockAdjustment

CENT = Decimal('0.01')


class InventoryError(Exception):
    """A stock or price change that can't be made, e.g. taking stock below zero."""


def lock_records(record_ids):
    """Lock the given records for the rest of the transaction and return them by pk.

    Rows are locked in pk order so two transactions locking overlapping sets can't deadlock.
    """
    return Record.objects.select_for_update().order_by('pk').in_bulk(record_ids)


def apply_stock_change(record, change, *, reason, user=None, note=''):
    """Change the stock of a record the caller has already locked (see lock_records) and log it."""
    new_stock = record.stock + change
    if new_stock < 0:
        raise InventoryError(f'"{record.title}" only has {record.stock} in stock, so it can\'t go down by {-change}.')
    record.stock = new_stock
    record.save(update_fields=['stock', 'updated_at'])
    return StockAdjustment.objects.create(
        record=record, user=user, change=change, stock_after=new_stock, reason=reason, note=note
    )


@transaction.atomic
def adjust_stock(record, change, *, user, reason, note=''):
    """A manual stock adjustment by staff (delivery, stock-take correction, damage)."""
    if change == 0:
        raise InventoryError('Enter a change other than zero.')
    locked = lock_records([record.pk])[record.pk]
    adjustment = apply_stock_change(locked, change, reason=reason, user=user, note=note)
    record.stock = locked.stock
    return adjustment


def log_initial_stock(record, *, user):
    """Record the opening stock of a newly added record."""
    return StockAdjustment.objects.create(
        record=record, user=user, change=record.stock, stock_after=record.stock, reason=StockAdjustment.Reason.INITIAL
    )


@transaction.atomic
def set_price(record, new_price, *, user, note=''):
    """Change one record's price."""
    locked = lock_records([record.pk])[record.pk]
    new_price = Decimal(new_price).quantize(CENT)
    if new_price < 0:
        raise InventoryError('Prices can\'t be negative.')
    if new_price == locked.price:
        raise InventoryError(f'"{record.title}" already costs {new_price}.')
    change = PriceChange.objects.create(
        record=locked, user=user, old_price=locked.price, new_price=new_price, note=note
    )
    locked.price = new_price
    locked.save(update_fields=['price', 'updated_at'])
    record.price = new_price
    return change


def adjusted_price(price, percent):
    """``price`` changed by ``percent`` per cent, rounded to the cent."""
    return (price * (1 + Decimal(percent) / 100)).quantize(CENT, rounding=ROUND_HALF_UP)


@transaction.atomic
def bulk_change_price(*, percent, user, genre=None, format='', note=''):
    """Raise or cut prices by a percentage for every record in a genre and/or format.

    Returns the PriceChange entries, which share one batch id. Records whose rounded price
    doesn't change are skipped.
    """
    if genre is None and not format:
        raise InventoryError('Choose a genre, a format or both.')
    if not percent:
        raise InventoryError('Enter a percentage other than zero.')
    records = Record.objects.all()
    if genre is not None:
        records = records.filter(genre=genre)
    if format:
        records = records.filter(format=format)

    batch, now = uuid.uuid4(), timezone.now()
    changes, changed = [], []
    for record in lock_records(list(records.values_list('pk', flat=True))).values():
        new_price = adjusted_price(record.price, percent)
        if new_price == record.price:
            continue
        changes.append(PriceChange(
            record=record, user=user, old_price=record.price, new_price=new_price,
            percent=percent, batch=batch, note=note,
        ))
        record.price, record.updated_at = new_price, now
        changed.append(record)
    Record.objects.bulk_update(changed, ['price', 'updated_at'])
    return PriceChange.objects.bulk_create(changes)
