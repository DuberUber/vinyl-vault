import zlib
from decimal import Decimal

from django import template
from django.conf import settings

register = template.Library()


@register.filter
def currency(amount):
    """Format a price with the site currency, e.g. 12.5 -> €12.50."""
    if amount in (None, ''):
        return ''
    return f'{settings.CURRENCY_SYMBOL}{Decimal(str(amount)):,.2f}'


@register.filter
def sleeve_hue(text):
    """A stable colour hue (0-359) derived from text, used to tint the generated sleeves and centre labels."""
    return zlib.crc32(str(text).encode()) % 360


@register.filter
def signed(value):
    """Show a number with an explicit sign, e.g. 3 -> +3, -2 -> −2 (for stock and price changes)."""
    if value in (None, ''):
        return ''
    return f'+{value}' if value > 0 else f'−{abs(value)}' if value < 0 else '0'
