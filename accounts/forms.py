from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm

from core.forms import BootstrapFormMixin

User = get_user_model()


class UniqueEmailMixin:
    def clean_email(self):
        email = self.cleaned_data['email']
        others = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            others = others.exclude(pk=self.instance.pk)
        if others.exists():
            raise forms.ValidationError('An account with this email address already exists.')
        return email


class SignupForm(BootstrapFormMixin, UniqueEmailMixin, UserCreationForm):
    """Registration with Django's password validators (the old form stored any password)."""

    email = forms.EmailField()

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ['username', 'email']


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    pass


class ProfileForm(BootstrapFormMixin, UniqueEmailMixin, forms.ModelForm):
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']


class StyledPasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
    pass
