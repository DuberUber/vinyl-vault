"""Small factories shared by the test suites."""
from decimal import Decimal
from itertools import count

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from catalog.models import Artist, Genre, Record

_catalogue_numbers = count(1)


def make_record(title='Blue Train', artist='John Coltrane', genre='Jazz', **fields):
    """Create a record, adding the artist and genre if needed. Each call gets a fresh catalogue number."""
    fields.setdefault('label', 'Blue Note')
    fields.setdefault('catalogue_number', f'TEST {next(_catalogue_numbers):04d}')
    fields.setdefault('price', Decimal('20.00'))
    fields.setdefault('stock', 3)
    return Record.objects.create(
        title=title,
        artist=Artist.objects.get_or_create(name=artist)[0],
        genre=Genre.objects.get_or_create(name=genre)[0],
        **fields,
    )


def make_user(username, *groups, **fields):
    """Create a user, optionally in the named staff groups (created by the staffdash data migration)."""
    user = get_user_model().objects.create_user(username, email=f'{username}@example.com', **fields)
    if groups:
        user.groups.set(Group.objects.filter(name__in=groups))
    return user
