from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse


class Cart(models.Model):
    """A signed-in customer's saved cart (one per user). Guests keep theirs in the session until they log in."""

    user       = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart for {self.user}"

    @property
    def total(self):
        return sum((item.subtotal for item in self.items.all()), Decimal('0.00'))

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items.all())


class CartItem(models.Model):
    cart     = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    # No reverse accessor: the catalog doesn't need to know about carts.
    record   = models.ForeignKey('catalog.Record', on_delete=models.CASCADE, related_name='+')
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['added_at', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['cart', 'record'], name='unique_record_per_cart'),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.record}"

    @property
    def subtotal(self):
        return self.record.price * self.quantity


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending payment'
        PAID = 'paid', 'Paid'
        SHIPPED = 'shipped', 'Shipped'
        CANCELLED = 'cancelled', 'Cancelled'

    # Statuses that count as a sale on the staff dashboard.
    SALE_STATUSES = [Status.PAID, Status.SHIPPED]

    user             = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders')
    status           = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    full_name        = models.CharField(max_length=150)
    email            = models.EmailField()
    shipping_address = models.TextField()
    # Stored rather than computed so the order keeps the amount actually charged.
    total            = models.DecimalField(max_digits=10, decimal_places=2)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)
    paid_at          = models.DateTimeField(null=True, blank=True)
    shipped_at       = models.DateTimeField(null=True, blank=True)
    cancelled_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [
            models.Index(fields=['user', '-created_at'], name='order_user_recent_idx'),
            models.Index(fields=['status', '-created_at'], name='order_status_recent_idx'),
        ]
        permissions = [('manage_orders', 'Can mark orders paid or shipped and cancel them')]

    def __str__(self):
        return f"Order {self.number}"

    def get_absolute_url(self):
        return reverse('orders:detail', args=[self.pk])

    @property
    def number(self):
        return f"VV-{self.pk:06d}"

    @property
    def customer_can_cancel(self):
        """Customers can cancel until they've paid; after that it's up to the sales team."""
        return self.status == self.Status.PENDING

    @property
    def can_cancel(self):
        return self.status in (self.Status.PENDING, self.Status.PAID)

    @property
    def can_mark_paid(self):
        return self.status == self.Status.PENDING

    @property
    def can_mark_shipped(self):
        return self.status == self.Status.PAID


class OrderItem(models.Model):
    order      = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    # SET_NULL keeps order history if a record is later removed from the shop; the details below are
    # copied at checkout so the order still reads correctly after any catalogue edit.
    record     = models.ForeignKey('catalog.Record', on_delete=models.SET_NULL, null=True, related_name='+')
    title      = models.CharField(max_length=200)
    artist     = models.CharField(max_length=200)
    format     = models.CharField(max_length=30)
    condition  = models.CharField(max_length=20)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    quantity   = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ['pk']

    def __str__(self):
        return f"{self.quantity} × {self.artist} – {self.title}"

    @property
    def subtotal(self):
        return self.unit_price * self.quantity
