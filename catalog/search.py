from django.db.models import Q

from .models import Grade, catalogue_key

# Sort keys accepted from the query string, mapped to model ordering (with a stable tie-breaker).
SORT_ORDERING = {
    'title': ('title', 'pk'),
    'artist': ('artist__name', 'title', 'pk'),
    'price': ('price', 'pk'),
    '-price': ('-price', 'pk'),
    'year': ('release_year', 'pk'),
    '-year': ('-release_year', 'pk'),
    'newest': ('-created_at', '-pk'),
}


def text_query(q):
    """Case-insensitive match on title, artist name, label or catalogue number."""
    match = Q(title__icontains=q) | Q(artist__name__icontains=q) | Q(label__icontains=q)
    # Compare catalogue numbers by letters and digits only, so "blp-4003" finds "BLP 4003".
    key = catalogue_key(q)
    if key:
        match |= Q(catalogue_key__icontains=key)
    return match


def build_search_query(*, q='', genre=None, format=(), condition='', min_price=None, max_price=None,
                       rare=False, in_stock=False):
    """Combine the (all optional) search criteria into a single Q object; unset criteria are left out.

    ``condition`` is a minimum vinyl grade: "VG+" matches VG+, NM and M records.
    """
    query = Q()
    q = q.strip()
    if q:
        query &= text_query(q)
    if genre is not None:
        query &= Q(genre=genre)
    if format:
        query &= Q(format__in=format)
    if condition:
        query &= Q(media_grade__in=Grade.at_least(condition))
    if min_price is not None:
        query &= Q(price__gte=min_price)
    if max_price is not None:
        query &= Q(price__lte=max_price)
    if rare:
        query &= Q(is_rare=True)
    if in_stock:
        query &= Q(stock__gt=0)
    return query


def search_records(queryset, *, sort='', **criteria):
    """Apply the shop's search criteria (see build_search_query) and sort order to a Record queryset."""
    ordering = SORT_ORDERING.get(sort, SORT_ORDERING['title'])
    return queryset.filter(build_search_query(**criteria)).order_by(*ordering)
