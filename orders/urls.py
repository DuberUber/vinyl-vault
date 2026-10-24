from django.urls import path

from . import views

app_name = 'orders'

urlpatterns = [
    # Shopping cart (guests and customers)
    path('cart/', views.cart_detail, name='cart'),
    path('cart/add/<int:record_id>/', views.add_to_cart, name='cart_add'),
    path('cart/update/<int:record_id>/', views.update_item, name='cart_update'),
    path('cart/remove/<int:record_id>/', views.remove_item, name='cart_remove'),

    # Checkout and order history
    path('', views.order_list, name='list'),
    path('checkout/', views.checkout, name='checkout'),
    path('<int:order_id>/', views.order_detail, name='detail'),
    path('<int:order_id>/cancel/', views.cancel_order, name='cancel'),
]
