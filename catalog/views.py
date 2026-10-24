from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from django.views.generic import ListView

from .forms import RecordSearchForm
from .models import Artist, Genre, Record
from .search import search_records

PAGE_SIZE = 12
RECORD_RELATIONS = ('artist', 'genre')


def get_search_results(data):
    """Validate search parameters and return (form, filtered records); invalid fields are ignored."""
    form = RecordSearchForm(data or None)
    filters = {}
    if form.is_bound:
        form.is_valid()  # populates cleaned_data with the fields that did validate
        filters = form.cleaned_data
    records = search_records(Record.objects.select_related(*RECORD_RELATIONS), **filters)
    return form, records


def home(request):
    in_stock = Record.objects.filter(stock__gt=0).select_related(*RECORD_RELATIONS)
    return render(request, 'catalog/home.html', {
        'rare_picks': in_stock.filter(is_rare=True).order_by('-price', 'pk')[:4],
        'new_arrivals': in_stock.order_by('-created_at', '-pk')[:8],
        'genres': Genre.objects.annotate(record_count=Count('records', filter=Q(records__stock__gt=0))),
    })


class RecordListView(ListView):
    template_name = 'catalog/record_list.html'
    context_object_name = 'records'
    paginate_by = PAGE_SIZE

    def get_search_data(self):
        return self.request.GET

    def get_queryset(self):
        self.form, records = get_search_results(self.get_search_data())
        return records

    def get_context_data(self, **kwargs):
        return super().get_context_data(form=self.form, **kwargs)


class GenreRecordListView(RecordListView):
    """The shop pre-filtered to one genre (reached from the navigation menu)."""

    def get_search_data(self):
        self.genre = get_object_or_404(Genre, slug=self.kwargs['slug'])
        data = self.request.GET.copy()
        data['genre'] = self.genre.pk
        return data

    def get_context_data(self, **kwargs):
        return super().get_context_data(genre=self.genre, **kwargs)


@require_GET
def record_search_api(request):
    """JSON version of the shop search, accepting the same query parameters."""
    form, records = get_search_results(request.GET)
    if form.is_bound and not form.is_valid():
        return JsonResponse({'errors': form.errors.get_json_data()}, status=400)
    page = Paginator(records, PAGE_SIZE).get_page(request.GET.get('page'))
    return JsonResponse({
        'count': page.paginator.count,
        'page': page.number,
        'num_pages': page.paginator.num_pages,
        'results': [
            {
                'id': record.pk,
                'title': record.title,
                'artist': record.artist.name,
                'genre': record.genre.name,
                'label': record.label,
                'catalogue_number': record.catalogue_number,
                'release_year': record.release_year,
                'format': record.format,
                'media_grade': record.media_grade,
                'sleeve_grade': record.sleeve_grade,
                'is_rare': record.is_rare,
                'price': str(record.price),
                'stock': record.stock,
                'url': request.build_absolute_uri(record.get_absolute_url()),
            }
            for record in page
        ],
    })


def record_detail(request, record_id):
    record = get_object_or_404(Record.objects.select_related(*RECORD_RELATIONS), pk=record_id)
    more_by_artist = (
        record.artist.records.exclude(pk=record.pk).select_related(*RECORD_RELATIONS).order_by('-stock', 'title')[:4]
    )
    return render(request, 'catalog/record_detail.html', {'record': record, 'more_by_artist': more_by_artist})


def artist_detail(request, artist_id):
    artist = get_object_or_404(Artist, pk=artist_id)
    records = artist.records.select_related(*RECORD_RELATIONS).order_by('release_year', 'title')
    return render(request, 'catalog/artist_detail.html', {'artist': artist, 'records': records})
