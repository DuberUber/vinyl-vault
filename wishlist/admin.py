from django.contrib import admin

from .models import WishlistItem


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ['user', 'record', 'price_when_added', 'in_stock_when_added', 'added_at']
    list_select_related = ['user', 'record']
    search_fields = ['user__username', 'record__title', 'record__artist__name']
    autocomplete_fields = ['user', 'record']
