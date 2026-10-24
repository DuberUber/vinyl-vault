from django.urls import path

from . import views

app_name = 'catalog'

urlpatterns = [
    path('', views.home, name='home'),

    # Searchable, filterable list of every record, and the same search as JSON
    path('records/', views.RecordListView.as_view(), name='record_list'),
    path('records/api/', views.record_search_api, name='record_search_api'),
    path('records/<int:record_id>/', views.record_detail, name='record_detail'),

    # Browse by genre or artist
    path('genres/<slug:slug>/', views.GenreRecordListView.as_view(), name='genre_records'),
    path('artists/<int:artist_id>/', views.artist_detail, name='artist_detail'),
]
