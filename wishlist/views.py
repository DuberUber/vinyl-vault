from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from catalog.models import Record
from core.utils import redirect_back
from orders.cart import CartError

from . import services
from .models import WishlistItem


def wants_json(request):
    return 'application/json' in request.headers.get('Accept', '')


@login_required
def wishlist_detail(request):
    items = WishlistItem.objects.filter(user=request.user).select_related('record__artist', 'record__genre')
    return render(request, 'wishlist/wishlist_detail.html', {'items': items})


@require_POST
def toggle(request, record_id):
    """The heart button: save or unsave a record. Answers with JSON for the in-page toggle, else redirects."""
    record = get_object_or_404(Record, pk=record_id)
    if not request.user.is_authenticated:
        if wants_json(request):
            return JsonResponse({'login_url': f"{reverse('accounts:login')}?next={record.get_absolute_url()}"}, status=401)
        return redirect_to_login(record.get_absolute_url())

    saved = services.toggle(request.user, record)
    if wants_json(request):
        ids, news = services.summary(request.user)
        return JsonResponse({'saved': saved, 'count': len(ids), 'news': news})
    if saved:
        messages.success(request, f'Saved "{record.title}" to your wishlist.')
    else:
        messages.info(request, f'Removed "{record.title}" from your wishlist.')
    return redirect_back(request, record)


@login_required
@require_POST
def move_to_cart(request, record_id):
    item = get_object_or_404(WishlistItem.objects.select_related('record'), user=request.user, record_id=record_id)
    try:
        services.move_to_cart(request.user, item.record)
    except CartError as error:
        messages.error(request, str(error))
        return redirect('wishlist:detail')
    messages.success(request, f'Moved "{item.record.title}" to your cart.')
    return redirect('wishlist:detail')
