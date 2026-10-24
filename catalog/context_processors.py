from .models import Genre


def genres(request):
    """Expose the genre list to every template for the navigation menu."""
    return {'nav_genres': Genre.objects.order_by('name')}
