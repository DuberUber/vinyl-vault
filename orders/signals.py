from django.contrib import messages
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .cart import merge_session_cart


@receiver(user_logged_in, dispatch_uid='orders.merge_session_cart')
def merge_guest_cart(sender, request, user, **kwargs):
    """Carry what a guest put in their cart over to their saved cart when they log in (or sign up)."""
    session = getattr(request, 'session', None)
    if session is None:
        return
    for note in merge_session_cart(session, user):
        messages.warning(request, note, fail_silently=True)
