from django.urls import path

from . import views

app_name = 'wishlist'

urlpatterns = [
    path('', views.wishlist_detail, name='detail'),
    path('toggle/<int:record_id>/', views.toggle, name='toggle'),
    path('<int:record_id>/move-to-cart/', views.move_to_cart, name='move_to_cart'),
]
