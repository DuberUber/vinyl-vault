from django import forms

from core.forms import BootstrapFormMixin

from .models import Artist, Genre, Grade, Record


class RecordForm(BootstrapFormMixin, forms.ModelForm):
    """Add or edit a record. The artist is typed by name and matched (or added) on save.

    Price and stock are only set when a record is first added; after that they change through
    the logged pricing and stock-adjustment tools.
    """

    artist_name = forms.CharField(label='Artist', max_length=200)

    class Meta:
        model = Record
        fields = [
            'title', 'artist_name', 'genre', 'label', 'catalogue_number', 'format', 'release_year',
            'media_grade', 'sleeve_grade', 'pressing_notes', 'is_rare', 'price', 'stock',
        ]
        widgets = {'pressing_notes': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            del self.fields['price']
            del self.fields['stock']
            self.fields['artist_name'].initial = self.instance.artist.name

    def clean_artist_name(self):
        return ' '.join(self.cleaned_data['artist_name'].split())

    def save(self, commit=True):
        name = self.cleaned_data['artist_name']
        artist = Artist.objects.filter(name__iexact=name).first()
        self.instance.artist = artist or Artist.objects.create(name=name)
        return super().save(commit)


class RecordSearchForm(BootstrapFormMixin, forms.Form):
    """Validates the shop's GET parameters; invalid fields are dropped rather than applied."""

    SORT_CHOICES = [
        ('title', 'Title (A-Z)'),
        ('artist', 'Artist (A-Z)'),
        ('price', 'Price: low to high'),
        ('-price', 'Price: high to low'),
        ('-year', 'Release year: newest'),
        ('year', 'Release year: oldest'),
        ('newest', 'Recently added'),
    ]

    q = forms.CharField(
        label='Search',
        required=False,
        max_length=100,
        widget=forms.SearchInput(attrs={'placeholder': 'Title, artist, label or cat. no.'}),
    )
    genre = forms.ModelChoiceField(
        queryset=Genre.objects.order_by('name'), required=False, empty_label='All genres'
    )
    format = forms.MultipleChoiceField(
        choices=Record.Format.choices, required=False, widget=forms.CheckboxSelectMultiple
    )
    condition = forms.ChoiceField(
        label='Vinyl grade at least',
        choices=[('', 'Any grade')] + Grade.choices,
        required=False,
    )
    min_price = forms.DecimalField(label='Min price', required=False, min_value=0, decimal_places=2)
    max_price = forms.DecimalField(label='Max price', required=False, min_value=0, decimal_places=2)
    rare = forms.BooleanField(label='Rare finds only', required=False)
    in_stock = forms.BooleanField(label='In stock only', required=False)
    sort = forms.ChoiceField(choices=SORT_CHOICES, required=False)

    def clean(self):
        cleaned_data = super().clean()
        low, high = cleaned_data.get('min_price'), cleaned_data.get('max_price')
        if low is not None and high is not None and low > high:
            self.add_error('max_price', 'Max price must be at least the min price.')
        return cleaned_data
