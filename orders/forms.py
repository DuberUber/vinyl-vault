from django import forms

from core.forms import BootstrapFormMixin

from .models import Order

MAX_QUANTITY = 99


class AddToCartForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, max_value=MAX_QUANTITY, initial=1)


class UpdateQuantityForm(forms.Form):
    # Zero removes the line.
    quantity = forms.IntegerField(min_value=0, max_value=MAX_QUANTITY)


class CheckoutForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Order
        fields = ['full_name', 'email', 'shipping_address']
        widgets = {'shipping_address': forms.Textarea(attrs={'rows': 3})}
