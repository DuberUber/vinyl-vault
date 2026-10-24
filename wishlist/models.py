from django.conf import settings
from django.db import models


class WishlistItem(models.Model):
    """A record a customer wants, remembering its price and availability when they saved it."""

    user                = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlist_items'
    )
    record              = models.ForeignKey('catalog.Record', on_delete=models.CASCADE, related_name='wishlist_items')
    price_when_added    = models.DecimalField(max_digits=8, decimal_places=2)
    in_stock_when_added = models.BooleanField(default=True)
    added_at            = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-added_at', '-pk']
        constraints = [
            models.UniqueConstraint(fields=['user', 'record'], name='unique_record_per_wishlist'),
        ]

    def __str__(self):
        return f'{self.user} wants {self.record}'

    @property
    def price_drop(self):
        """How much cheaper the record is now than when it was saved (zero if it isn't)."""
        return max(self.price_when_added - self.record.price, 0)

    @property
    def back_in_stock(self):
        return not self.in_stock_when_added and self.record.in_stock

    @property
    def has_news(self):
        return bool(self.price_drop) or self.back_in_stock
