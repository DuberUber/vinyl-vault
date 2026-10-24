from django.contrib import admin
from django.db.models import Count

from . import services
from .models import Artist, Genre, PriceChange, Record, StockAdjustment


class RecordCountMixin:
    def get_queryset(self, request):
        return super().get_queryset(request).annotate(record_count=Count('records'))

    @admin.display(ordering='record_count', description='Records')
    def record_count(self, obj):
        return obj.record_count


@admin.register(Genre)
class GenreAdmin(RecordCountMixin, admin.ModelAdmin):
    list_display = ['name', 'slug', 'record_count']
    search_fields = ['name']
    prepopulated_fields = {'slug': ['name']}


class RecordInline(admin.TabularInline):
    model = Record
    fields = ['title', 'label', 'catalogue_number', 'format', 'media_grade', 'price', 'stock']
    readonly_fields = ['price', 'stock']
    extra = 0
    show_change_link = True


@admin.register(Artist)
class ArtistAdmin(RecordCountMixin, admin.ModelAdmin):
    list_display = ['name', 'record_count']
    search_fields = ['name']
    inlines = [RecordInline]


@admin.register(Record)
class RecordAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'artist', 'label', 'catalogue_number', 'format', 'media_grade', 'sleeve_grade', 'is_rare',
        'price', 'stock',
    ]
    list_filter = ['format', 'media_grade', 'is_rare', 'genre']
    list_select_related = ['artist', 'genre']
    search_fields = ['title', 'artist__name', 'label', 'catalogue_number']
    autocomplete_fields = ['artist', 'genre']
    # Price and stock change through the staff dashboard, which logs every change.
    readonly_fields = ['price', 'stock', 'created_at', 'updated_at']

    def get_readonly_fields(self, request, obj=None):
        # A new record needs its opening price and stock.
        return ['created_at', 'updated_at'] if obj is None else self.readonly_fields

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            services.log_initial_stock(obj, user=request.user)


class ReadOnlyLogAdmin(admin.ModelAdmin):
    list_select_related = ['record', 'user']
    search_fields = ['record__title', 'record__catalogue_number', 'user__username']
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(ReadOnlyLogAdmin):
    list_display = ['created_at', 'record', 'change', 'stock_after', 'reason', 'user', 'note']
    list_filter = ['reason']


@admin.register(PriceChange)
class PriceChangeAdmin(ReadOnlyLogAdmin):
    list_display = ['created_at', 'record', 'old_price', 'new_price', 'percent', 'user', 'note']
