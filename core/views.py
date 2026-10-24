from django.db import connection
from django.http import JsonResponse


def health(request):
    """Liveness/readiness probe for load balancers and uptime checks; fails if the database is unreachable."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
    return JsonResponse({'status': 'ok'})
