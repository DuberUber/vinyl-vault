from django.contrib import admin
from django.urls import include, path

# Each app owns its URLconf and is mounted under its own namespace (catalog:record_detail, staffdash:home, ...).
urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls", namespace="core")),
    path("accounts/", include("accounts.urls", namespace="accounts")),
    path("orders/", include("orders.urls", namespace="orders")),
    path("wishlist/", include("wishlist.urls", namespace="wishlist")),
    path("staff/", include("staffdash.urls", namespace="staffdash")),
    path("", include("catalog.urls", namespace="catalog")),
]
