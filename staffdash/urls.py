from django.urls import path

from . import views

app_name = 'staffdash'

urlpatterns = [
    path('', views.DashboardView.as_view(), name='home'),

    # Inventory: record details and logged stock adjustments
    path('inventory/', views.InventoryListView.as_view(), name='inventory'),
    path('inventory/add/', views.RecordCreateView.as_view(), name='record_add'),
    path('inventory/<int:record_id>/edit/', views.RecordUpdateView.as_view(), name='record_edit'),
    path('inventory/<int:record_id>/stock/', views.StockAdjustView.as_view(), name='stock_adjust'),
    path('inventory/log/', views.StockLogView.as_view(), name='stock_log'),

    # Pricing: single and bulk percentage changes, logged
    path('pricing/', views.PricingView.as_view(), name='pricing'),
    path('pricing/<int:record_id>/', views.PriceUpdateView.as_view(), name='price_update'),
    path('pricing/log/', views.PriceLogView.as_view(), name='price_log'),

    # Orders: payment, shipping and cancellation
    path('orders/', views.OrderListView.as_view(), name='orders'),
    path('orders/<int:order_id>/', views.OrderDetailView.as_view(), name='order_detail'),
    path('orders/<int:order_id>/<str:action>/', views.OrderActionView.as_view(), name='order_action'),
]
