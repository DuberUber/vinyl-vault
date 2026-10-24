from . import services


def wishlist_summary(request):
    """Which records the user has saved (to fill in the heart buttons) and how many have news, for the nav badge."""
    if not request.user.is_authenticated:
        return {'wishlisted_ids': set()}
    ids, news = services.summary(request.user)
    return {'wishlisted_ids': ids, 'wishlist_count': len(ids), 'wishlist_news_count': news}
