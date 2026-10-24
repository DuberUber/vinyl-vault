from decimal import Decimal

from django import forms

from catalog.models import Genre, Record, StockAdjustment
from core.forms import BootstrapFormMixin

MAX_STOCK_CHANGE = 999


class StockAdjustmentForm(BootstrapFormMixin, forms.Form):
    change = forms.IntegerField(
        min_value=-MAX_STOCK_CHANGE, max_value=MAX_STOCK_CHANGE,
        help_text='Positive to add copies, negative to remove them.',
    )
    reason = forms.ChoiceField(
        choices=[(reason.value, reason.label) for reason in StockAdjustment.MANUAL_REASONS]
    )
    note = forms.CharField(max_length=200, required=False)

    def clean_change(self):
        change = self.cleaned_data['change']
        if change == 0:
            raise forms.ValidationError('Enter a change other than zero.')
        return change


class PriceForm(BootstrapFormMixin, forms.Form):
    price = forms.DecimalField(label='New price', min_value=0, max_digits=8, decimal_places=2)
    note = forms.CharField(max_length=200, required=False)


class BulkPriceForm(BootstrapFormMixin, forms.Form):
    genre = forms.ModelChoiceField(queryset=Genre.objects.order_by('name'), required=False, empty_label='Any genre')
    format = forms.ChoiceField(choices=[('', 'Any format')] + Record.Format.choices, required=False)
    percent = forms.DecimalField(
        label='Change (%)', min_value=Decimal('-90'), max_value=Decimal('200'), max_digits=5, decimal_places=2,
        help_text='E.g. 10 for a 10% rise, -15 for a 15% cut. Prices are rounded to the cent.',
    )
    note = forms.CharField(max_length=200, required=False)

    def clean_percent(self):
        percent = self.cleaned_data['percent']
        if percent == 0:
            raise forms.ValidationError('Enter a percentage other than zero.')
        return percent

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('genre') and not cleaned_data.get('format'):
            raise forms.ValidationError('Choose a genre, a format or both.')
        return cleaned_data
