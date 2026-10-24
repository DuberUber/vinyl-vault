import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.urls import reverse
from django.utils.text import slugify

FIRST_RELEASE_YEAR = 1948  # the first long-playing records
LAST_RELEASE_YEAR = 2100
DUPLICATE_PRESSING = 'A record with this label, catalogue number and format already exists.'


def normalise_catalogue_number(value):
    """Tidy a catalogue number for display: upper case, single spaces, plain hyphens ("blp – 4003" -> "BLP-4003")."""
    value = re.sub(r'\s*[\u2010-\u2015-]\s*', '-', value or '')
    return ' '.join(value.upper().split())


def catalogue_key(value):
    """Letters and digits only, so "BLP 4003", "BLP-4003" and "blp4003" all match the same pressing."""
    return re.sub(r'[^0-9A-Z]', '', (value or '').upper())


def normalise_label(value):
    return ' '.join((value or '').split())


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('catalog:genre_records', args=[self.slug])


class Artist(models.Model):
    name = models.CharField(max_length=200, unique=True)
    bio = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('catalog:artist_detail', args=[self.pk])


class Grade(models.TextChoices):
    """Goldmine grading scale, best first. Used for both the vinyl (media) and the sleeve."""

    MINT = 'M', 'Mint (M)'
    NEAR_MINT = 'NM', 'Near Mint (NM)'
    VERY_GOOD_PLUS = 'VG+', 'Very Good Plus (VG+)'
    VERY_GOOD = 'VG', 'Very Good (VG)'
    GOOD_PLUS = 'G+', 'Good Plus (G+)'
    GOOD = 'G', 'Good (G)'

    @classmethod
    def at_least(cls, grade):
        """The grades equal to or better than ``grade``, e.g. VG+ -> [M, NM, VG+]."""
        values = cls.values
        return values[:values.index(grade) + 1]


class Record(models.Model):
    """A pressing the shop has in stock (or has sold out of)."""

    class Format(models.TextChoices):
        LP = 'LP', 'LP'
        TWELVE_INCH = '12in', '12" single'
        SEVEN_INCH = '7in', '7" single'
        EP = 'EP', 'EP'
        BOX_SET = 'box', 'Box set'

    title            = models.CharField(max_length=200)
    # PROTECT: removing an artist or genre must not silently delete stock.
    artist           = models.ForeignKey(Artist, on_delete=models.PROTECT, related_name='records')
    genre            = models.ForeignKey(Genre, on_delete=models.PROTECT, related_name='records')
    label            = models.CharField(max_length=150)
    catalogue_number = models.CharField(
        max_length=50, help_text='As printed on the label or spine; case and spacing are normalised.'
    )
    # Derived from catalogue_number on save; used for search and the one-row-per-pressing constraint.
    catalogue_key    = models.CharField(max_length=50, editable=False, db_index=True)
    release_year     = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(FIRST_RELEASE_YEAR), MaxValueValidator(LAST_RELEASE_YEAR)],
        help_text='Year this pressing was released.',
    )
    format           = models.CharField(max_length=4, choices=Format.choices, default=Format.LP)
    media_grade      = models.CharField('vinyl grade', max_length=3, choices=Grade.choices, default=Grade.VERY_GOOD_PLUS)
    sleeve_grade     = models.CharField(max_length=3, choices=Grade.choices, default=Grade.VERY_GOOD_PLUS)
    pressing_notes   = models.TextField(blank=True, help_text='Matrix, country, reissue details, inserts...')
    is_rare          = models.BooleanField('rare', default=False)
    price            = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    stock            = models.PositiveIntegerField('copies in stock', default=1)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title', 'pk']
        constraints = [
            # One row per pressing: the same catalogue number on the same label and format is the same record.
            models.UniqueConstraint(
                Lower('label'), 'catalogue_key', 'format',
                name='unique_pressing',
                violation_error_message=DUPLICATE_PRESSING,
            ),
        ]
        permissions = [
            ('adjust_stock', 'Can adjust record stock'),
            ('change_price', 'Can change record prices'),
        ]

    def __str__(self):
        return f'{self.artist} – {self.title} ({self.get_format_display()})'

    def get_absolute_url(self):
        return reverse('catalog:record_detail', args=[self.pk])

    def normalise(self):
        self.label = normalise_label(self.label)
        self.catalogue_number = normalise_catalogue_number(self.catalogue_number)
        self.catalogue_key = catalogue_key(self.catalogue_number)

    def clean(self):
        self.normalise()
        # The unique constraint covers catalogue_key, which forms don't edit (so Django skips the constraint
        # check there); report a duplicate against the field the user typed instead.
        duplicate = Record.objects.filter(
            label__iexact=self.label, catalogue_key=self.catalogue_key, format=self.format
        ).exclude(pk=self.pk)
        if self.catalogue_key and duplicate.exists():
            raise ValidationError({'catalogue_number': DUPLICATE_PRESSING})

    def save(self, *args, **kwargs):
        # Normalise ORM writes too, not just validated forms.
        self.normalise()
        super().save(*args, **kwargs)

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def condition(self):
        """Short media/sleeve grading, e.g. "NM / VG+"."""
        return f'{self.media_grade} / {self.sleeve_grade}'


class StockAdjustment(models.Model):
    """An audit entry for every change to a record's stock: deliveries, corrections, sales and returns."""

    class Reason(models.TextChoices):
        INITIAL = 'initial', 'Initial stock'
        RECEIVED = 'received', 'Delivery received'
        CORRECTION = 'correction', 'Stock-take correction'
        DAMAGED = 'damaged', 'Damaged or lost'
        SALE = 'sale', 'Sold'
        RESTOCK = 'restock', 'Order cancelled'

    # Reasons staff can pick by hand; sales and cancellations are logged by checkout.
    MANUAL_REASONS = [Reason.RECEIVED, Reason.CORRECTION, Reason.DAMAGED]

    record      = models.ForeignKey(Record, on_delete=models.CASCADE, related_name='stock_adjustments')
    user        = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    change      = models.IntegerField()
    stock_after = models.PositiveIntegerField()
    reason      = models.CharField(max_length=12, choices=Reason.choices)
    note        = models.CharField(max_length=200, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return f'{self.record.title}: {self.change:+d} ({self.get_reason_display()})'


class PriceChange(models.Model):
    """An audit entry for a price change; a bulk change shares one ``batch`` id across its records."""

    record     = models.ForeignKey(Record, on_delete=models.CASCADE, related_name='price_changes')
    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    old_price  = models.DecimalField(max_digits=8, decimal_places=2)
    new_price  = models.DecimalField(max_digits=8, decimal_places=2)
    percent    = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True, help_text='Set for bulk percentage changes.'
    )
    batch      = models.UUIDField(null=True, blank=True, db_index=True)
    note       = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return f'{self.record.title}: {self.old_price} -> {self.new_price}'
