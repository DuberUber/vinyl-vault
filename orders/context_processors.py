from .cart import get_cart


def cart_summary(request):
    """Number of items in the visitor's cart (saved or session), for the navigation badge."""
    return {'cart_item_count': get_cart(request).count()}
