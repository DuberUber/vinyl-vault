from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.test import TestCase
from django.urls import reverse

from core.testing import make_record

from .models import Genre, Grade, Record, catalogue_key, normalise_catalogue_number
from .search import build_search_query, search_records


class CatalogueNumberTests(TestCase):
    def test_numbers_are_normalised_for_display(self):
        self.assertEqual(normalise_catalogue_number('  blp  4003 '), 'BLP 4003')
        self.assertEqual(normalise_catalogue_number('a – 77'), 'A-77')

    def test_key_ignores_case_spaces_and_punctuation(self):
        self.assertEqual(catalogue_key('BLP 4003'), catalogue_key('blp-4003'))
        self.assertEqual(catalogue_key('07863 66336-1'), '07863663361')

    def test_saving_normalises_label_number_and_key(self):
        record = make_record(label='  Blue   Note ', catalogue_number='blp 1577')

        record.refresh_from_db()
        self.assertEqual((record.label, record.catalogue_number, record.catalogue_key), ('Blue Note', 'BLP 1577', 'BLP1577'))

    def test_same_pressing_cannot_be_added_twice(self):
        make_record(label='Blue Note', catalogue_number='BLP 1577', format=Record.Format.LP)

        with self.assertRaises(IntegrityError):
            make_record(label='blue note', catalogue_number='BLP-1577', format=Record.Format.LP)

    def test_duplicate_pressing_is_a_validation_error_on_the_catalogue_number(self):
        existing = make_record(label='Blue Note', catalogue_number='BLP 1577')
        duplicate = Record(
            title='Copy', artist=existing.artist, genre=existing.genre, label='BLUE NOTE',
            catalogue_number='blp1577', format=existing.format, price=1, stock=1,
        )

        with self.assertRaises(ValidationError) as caught:
            duplicate.full_clean()

        self.assertIn('catalogue_number', caught.exception.message_dict)

    def test_same_number_is_fine_on_another_format_or_label(self):
        make_record(label='Factory', catalogue_number='FAC 73', format=Record.Format.TWELVE_INCH)
        make_record(label='Factory', catalogue_number='FAC 73', format=Record.Format.SEVEN_INCH)
        make_record(label='Other', catalogue_number='FAC 73', format=Record.Format.TWELVE_INCH)

        self.assertEqual(Record.objects.filter(catalogue_key='FAC73').count(), 3)


class RecordModelTests(TestCase):
    def test_str_and_condition(self):
        record = make_record(media_grade=Grade.NEAR_MINT, sleeve_grade=Grade.VERY_GOOD_PLUS)

        self.assertEqual(str(record), 'John Coltrane – Blue Train (LP)')
        self.assertEqual(record.condition, 'NM / VG+')

    def test_grades_at_least(self):
        self.assertEqual(Grade.at_least('VG+'), ['M', 'NM', 'VG+'])
        self.assertEqual(Grade.at_least('M'), ['M'])
        self.assertEqual(len(Grade.at_least('G')), 6)

    def test_release_year_is_validated(self):
        record = make_record(release_year=1066)

        with self.assertRaises(ValidationError):
            record.full_clean()

    def test_genre_slug_is_generated(self):
        self.assertEqual(Genre.objects.create(name='Soul & Funk').slug, 'soul-funk')


class SearchTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.blue_train = make_record(
            'Blue Train', 'John Coltrane', 'Jazz', label='Blue Note', catalogue_number='BLP 1577', release_year=1957,
            media_grade=Grade.VERY_GOOD_PLUS, is_rare=True, price=Decimal('450.00'), stock=1,
        )
        cls.moanin = make_record(
            "Moanin'", 'Art Blakey & The Jazz Messengers', 'Jazz', label='Blue Note', catalogue_number='BLP 4003',
            release_year=1959, media_grade=Grade.VERY_GOOD, is_rare=True, price=Decimal('210.00'), stock=0,
        )
        cls.blue_monday = make_record(
            'Blue Monday', 'New Order', 'Electronic', label='Factory', catalogue_number='FAC 73', release_year=1983,
            format=Record.Format.TWELVE_INCH, media_grade=Grade.NEAR_MINT, price=Decimal('35.00'), stock=4,
        )
        cls.jazz = cls.blue_train.genre

    def search(self, **params):
        return list(search_records(Record.objects.all(), **params))


class SearchRecordsTests(SearchTestCase):
    def test_no_criteria_returns_everything_sorted_by_title(self):
        self.assertEqual(self.search(), [self.blue_monday, self.blue_train, self.moanin])

    def test_title_search_is_case_insensitive(self):
        self.assertEqual(self.search(q='bLUE tRAIN'), [self.blue_train])

    def test_search_matches_artist_name(self):
        self.assertEqual(self.search(q='messengers'), [self.moanin])

    def test_search_matches_label(self):
        self.assertEqual(self.search(q='factory'), [self.blue_monday])

    def test_search_matches_catalogue_number_however_it_is_typed(self):
        for q in ['BLP 4003', 'blp-4003', 'blp4003', '4003']:
            with self.subTest(q=q):
                self.assertEqual(self.search(q=q), [self.moanin])

    def test_genre_filter(self):
        self.assertEqual(self.search(genre=self.jazz), [self.blue_train, self.moanin])

    def test_format_filter(self):
        self.assertEqual(self.search(format=['12in']), [self.blue_monday])
        self.assertEqual(self.search(format=['12in', 'LP']), [self.blue_monday, self.blue_train, self.moanin])

    def test_condition_is_a_minimum_vinyl_grade(self):
        self.assertEqual(self.search(condition='NM'), [self.blue_monday])
        self.assertEqual(self.search(condition='VG+'), [self.blue_monday, self.blue_train])
        self.assertEqual(self.search(condition='VG'), [self.blue_monday, self.blue_train, self.moanin])

    def test_price_range_bounds_are_inclusive(self):
        self.assertEqual(self.search(min_price=Decimal('35'), max_price=Decimal('210')), [self.blue_monday, self.moanin])

    def test_rare_and_in_stock_filters(self):
        self.assertEqual(self.search(rare=True), [self.blue_train, self.moanin])
        self.assertEqual(self.search(rare=True, in_stock=True), [self.blue_train])

    def test_criteria_are_combined_into_one_q_object(self):
        query = build_search_query(
            q='blue', genre=self.jazz, format=['LP'], condition='VG+', min_price=Decimal('1'),
            max_price=Decimal('500'), rare=True, in_stock=True,
        )

        self.assertIsInstance(query, Q)
        self.assertEqual(query.connector, 'AND')
        self.assertEqual(len(query.children), 8)  # text match (an OR), genre, format, grade, min, max, rare, stock
        self.assertEqual(list(Record.objects.filter(query)), [self.blue_train])

    def test_empty_criteria_match_everything(self):
        self.assertEqual(build_search_query(q='   ', format=[], condition=''), Q())

    def test_sorting(self):
        self.assertEqual(self.search(sort='-price'), [self.blue_train, self.moanin, self.blue_monday])
        self.assertEqual(self.search(sort='artist'), [self.moanin, self.blue_train, self.blue_monday])
        self.assertEqual(self.search(sort='-year'), [self.blue_monday, self.moanin, self.blue_train])
        self.assertEqual(self.search(sort='newest'), [self.blue_monday, self.moanin, self.blue_train])

    def test_unknown_sort_falls_back_to_title(self):
        self.assertEqual(self.search(sort='stock; DROP TABLE'), [self.blue_monday, self.blue_train, self.moanin])


class RecordListPageTests(SearchTestCase):
    def get(self, *args, **params):
        return self.client.get(reverse('catalog:record_list') + ''.join(args), params)

    def test_query_string_filters_the_list(self):
        response = self.get(q='blue', max_price='300')

        # "Blue Monday" by title, "Moanin'" by its Blue Note label; Blue Train is over the price limit.
        self.assertEqual(list(response.context['records']), [self.blue_monday, self.moanin])
        self.assertContains(response, 'value="blue"')

    def test_format_checkboxes_and_grade_filter(self):
        response = self.get('?format=LP&format=EP&condition=VG%2B')

        self.assertEqual(list(response.context['records']), [self.blue_train])
        self.assertContains(response, 'value="LP" class="form-check-input" id="id_format_0" checked')

    def test_invalid_values_are_ignored_and_reported(self):
        response = self.get(condition='mint-ish', min_price='cheap')

        self.assertEqual(len(response.context['records']), 3)
        self.assertContains(response, 'Select a valid choice.')
        self.assertContains(response, 'Enter a number.')

    def test_min_price_above_max_price_is_reported(self):
        response = self.get(min_price='300', max_price='5')

        self.assertContains(response, 'Max price must be at least the min price.')
        self.assertEqual(list(response.context['records']), [self.blue_train])

    def test_results_are_paginated_and_links_keep_filters(self):
        for i in range(13):
            make_record(f'Session {i:02}', 'House Band', 'Jazz', label='Sessions', catalogue_number=f'S {i}')

        first = self.get(q='session')
        second = self.get(q='session', page=2)

        self.assertEqual(first.context['paginator'].count, 13)
        self.assertEqual(len(first.context['records']), 12)
        self.assertEqual([r.title for r in second.context['records']], ['Session 12'])
        self.assertContains(first, 'href="?q=session&amp;page=2"')

    def test_list_uses_a_fixed_number_of_queries(self):
        # count + one page of records (artist/genre joined) + genres for the nav menu and for the filter form
        with self.assertNumQueries(4):
            self.get()

    def test_genre_page_prefilters_and_keeps_other_filters(self):
        response = self.client.get(reverse('catalog:genre_records', args=['jazz']), {'in_stock': 'on'})

        self.assertEqual(list(response.context['records']), [self.blue_train])
        self.assertEqual(response.context['genre'], self.jazz)

    def test_unknown_genre_is_404(self):
        self.assertEqual(self.client.get(reverse('catalog:genre_records', args=['polka'])).status_code, 404)


class RecordSearchApiTests(SearchTestCase):
    def test_lives_at_records_api(self):
        self.assertEqual(reverse('catalog:record_search_api'), '/records/api/')

    def test_returns_filtered_json(self):
        response = self.client.get(reverse('catalog:record_search_api'), {'q': 'jazz'})

        data = response.json()
        self.assertEqual(data['count'], 1)
        result = data['results'][0]
        self.assertEqual(result['title'], "Moanin'")
        self.assertEqual(result['artist'], 'Art Blakey & The Jazz Messengers')
        self.assertEqual(result['catalogue_number'], 'BLP 4003')
        self.assertEqual((result['format'], result['media_grade'], result['price']), ('LP', 'VG', '210.00'))
        self.assertTrue(result['url'].endswith(self.moanin.get_absolute_url()))

    def test_filters_combine(self):
        response = self.client.get(reverse('catalog:record_search_api') + '?q=blue&rare=on&in_stock=on&sort=-price')

        self.assertEqual([r['title'] for r in response.json()['results']], ['Blue Train'])

    def test_invalid_parameters_return_400(self):
        response = self.client.get(reverse('catalog:record_search_api'), {'max_price': '-1', 'format': 'cassette'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()['errors']), {'max_price', 'format'})


class RecordPageTests(SearchTestCase):
    def test_home_shows_rare_picks_and_new_arrivals_in_stock(self):
        response = self.client.get(reverse('catalog:home'))

        self.assertEqual(list(response.context['rare_picks']), [self.blue_train])
        self.assertEqual(list(response.context['new_arrivals']), [self.blue_monday, self.blue_train])
        self.assertContains(response, 'Vinyl Vault')

    def test_record_detail_shows_pressing_details(self):
        response = self.client.get(self.blue_train.get_absolute_url())

        self.assertContains(response, 'BLP 1577')
        self.assertContains(response, 'Very Good Plus (VG+)')
        self.assertContains(response, 'Last copy in stock')
        self.assertContains(response, reverse('orders:cart_add', args=[self.blue_train.pk]))
        self.assertContains(response, reverse('catalog:artist_detail', args=[self.blue_train.artist_id]))
        self.assertNotContains(response, reverse('staffdash:record_edit', args=[self.blue_train.pk]))

    def test_sold_out_record_offers_the_wishlist_instead(self):
        response = self.client.get(self.moanin.get_absolute_url())

        self.assertContains(response, 'Sold out')
        self.assertNotContains(response, reverse('orders:cart_add', args=[self.moanin.pk]))
        self.assertContains(response, reverse('wishlist:toggle', args=[self.moanin.pk]))

    def test_artist_page_lists_their_records(self):
        response = self.client.get(reverse('catalog:artist_detail', args=[self.moanin.artist_id]))

        self.assertEqual(list(response.context['records']), [self.moanin])

    def test_navigation_lists_genres(self):
        response = self.client.get(reverse('catalog:home'))

        self.assertContains(response, f'href="{reverse("catalog:genre_records", args=["electronic"])}"')

    def test_there_are_no_customer_listing_pages(self):
        for path in ['/records/add/', '/records/mine/', f'/records/{self.blue_train.pk}/edit/']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
