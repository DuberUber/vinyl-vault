import secrets
from datetime import timedelta
from decimal import Decimal

from decouple import config
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from catalog import services as inventory
from catalog.models import Artist, Genre, PriceChange, Record, StockAdjustment, catalogue_key
from orders.cart import DatabaseCart
from orders.models import CartItem, Order, OrderItem
from orders.services import snapshot_item
from staffdash.roles import INVENTORY, SALES
from wishlist.models import WishlistItem

ARTISTS = {
    'John Coltrane': 'Saxophonist and composer whose work moved from hard bop to modal and free jazz.',
    'Miles Davis': 'Trumpeter and bandleader at the centre of cool jazz, modal jazz and fusion.',
    'Cannonball Adderley': 'Alto saxophonist known for his soulful, bluesy hard bop.',
    'Art Blakey & The Jazz Messengers': 'The hard-bop finishing school, led from the drum stool by Art Blakey.',
    'Charles Mingus': 'Bassist, composer and bandleader with a fiery, gospel-tinged sound.',
    'Herbie Hancock': 'Pianist and keyboardist who took jazz into funk and electronics.',
    'Marvin Gaye': 'Motown singer and songwriter, from hit singles to concept albums.',
    'Stevie Wonder': 'Singer, songwriter and multi-instrumentalist behind a run of classic 1970s albums.',
    'Curtis Mayfield': 'Soul singer, guitarist and producer, founder of the Curtom label.',
    'Funkadelic': "George Clinton's psychedelic funk-rock collective.",
    'Fleetwood Mac': 'British-American rock band whose 1970s line-up sold millions.',
    'Pink Floyd': 'English rock band known for long-form, conceptual albums.',
    'Joy Division': 'Post-punk band from Salford, the first signing to Factory Records.',
    'Sonic Youth': 'New York noise-rock band built on alternate guitar tunings.',
    'The Beatles': 'The Liverpool four-piece that defined the 1960s.',
    'Black Sabbath': 'Birmingham band widely credited with inventing heavy metal.',
    'Aphex Twin': 'Electronic producer Richard D. James, from ambient to drill and bass.',
    'Daft Punk': 'Parisian house duo behind filtered disco and robot helmets.',
    'New Order': 'Formed from Joy Division, pioneers of electronic dance-rock.',
    'Rhythim Is Rhythim': 'Derrick May, one of the originators of Detroit techno.',
    'Kraftwerk': 'Düsseldorf electronic pioneers.',
    'Nas': 'Queensbridge rapper whose debut is a landmark of East Coast hip-hop.',
    'De La Soul': 'Long Island trio known for playful, sample-rich hip-hop.',
    'Wu-Tang Clan': 'Staten Island collective led by producer RZA.',
    'A Tribe Called Quest': 'Queens group that fused jazz samples and conscious rhymes.',
    'The Wailers': 'Bob Marley, Peter Tosh and Bunny Wailer, the roots of reggae.',
    'The Upsetters': "Lee \"Scratch\" Perry's studio band at the Black Ark.",
    'Augustus Pablo': 'Melodica player and producer central to roots and dub.',
    'The Specials': 'Coventry band at the heart of the 2 Tone ska revival.',
    'Nick Drake': 'English singer-songwriter whose three albums found fame after his death.',
    'Joni Mitchell': 'Canadian singer-songwriter and painter.',
}

# title, artist, genre, label, catalogue number, year, format, vinyl grade, sleeve grade, rare, price, stock, notes
RECORDS = [
    ('Blue Train', 'John Coltrane', 'Jazz', 'Blue Note', 'BLP 1577', 1957, 'LP', 'VG+', 'VG', True, '450.00', 1,
     'Mono first pressing, West 63rd labels, "ear" and RVG in the dead wax.'),
    ('A Love Supreme', 'John Coltrane', 'Jazz', 'Impulse!', 'A-77', 1965, 'LP', 'NM', 'VG+', True, '320.00', 1,
     'Original orange and black labels, laminated gatefold.'),
    ('Kind of Blue', 'Miles Davis', 'Jazz', 'Columbia', 'CL 1355', 1959, 'LP', 'VG', 'VG', True, '280.00', 0,
     'Six-eye mono pressing. Light surface marks, plays through cleanly.'),
    ("Somethin' Else", 'Cannonball Adderley', 'Jazz', 'Blue Note', 'BLP 1595', 1958, 'LP', 'VG+', 'VG+', True,
     '390.00', 1, 'Mono, with Miles Davis on trumpet.'),
    ("Moanin'", 'Art Blakey & The Jazz Messengers', 'Jazz', 'Blue Note', 'BLP 4003', 1959, 'LP', 'VG', 'G+', True,
     '210.00', 2, 'Sleeve has ring wear and a split along the bottom seam.'),
    ('Mingus Ah Um', 'Charles Mingus', 'Jazz', 'Columbia', 'CS 8171', 1959, 'LP', 'NM', 'NM', False, '34.99', 4,
     '180 g reissue cut from the original tapes.'),
    ('Head Hunters', 'Herbie Hancock', 'Jazz', 'Columbia', 'KC 32731', 1973, 'LP', 'VG+', 'VG', False, '45.00', 2, ''),
    ("What's Going On", 'Marvin Gaye', 'Soul & Funk', 'Tamla', 'TS 310', 1971, 'LP', 'VG+', 'VG+', False, '65.00', 2,
     'Original US gatefold.'),
    ('Songs in the Key of Life', 'Stevie Wonder', 'Soul & Funk', 'Tamla', 'T13-340C2', 1976, 'LP', 'VG+', 'VG',
     False, '55.00', 3, 'Double LP with the bonus 7" EP and printed lyric insert.'),
    ('Superfly', 'Curtis Mayfield', 'Soul & Funk', 'Curtom', 'CRS 8014-ST', 1972, 'LP', 'VG', 'VG', False, '40.00', 1,
     ''),
    ('Maggot Brain', 'Funkadelic', 'Soul & Funk', 'Westbound', 'WB 2007', 1971, 'LP', 'VG+', 'VG', True, '150.00', 1,
     'Original Westbound pressing.'),
    ('Move On Up', 'Curtis Mayfield', 'Soul & Funk', 'Buddah', '2011 080', 1971, '7in', 'VG+', 'G+', False, '18.00', 3,
     'UK single in a company sleeve.'),
    ('I Heard It Through the Grapevine', 'Marvin Gaye', 'Soul & Funk', 'Tamla', 'T 54176', 1968, '7in', 'VG', 'VG',
     False, '12.00', 5, ''),
    ('Rumours', 'Fleetwood Mac', 'Rock', 'Warner Bros.', 'BSK 3010', 1977, 'LP', 'NM', 'VG+', False, '38.00', 4,
     'With the original printed inner sleeve.'),
    ('The Dark Side of the Moon', 'Pink Floyd', 'Rock', 'Harvest', 'SHVL 804', 1973, 'LP', 'VG+', 'VG+', True,
     '240.00', 1, 'UK first pressing, solid blue triangle labels, both posters and stickers.'),
    ('Unknown Pleasures', 'Joy Division', 'Rock', 'Factory', 'FACT 10', 1979, 'LP', 'VG+', 'VG', True, '180.00', 1,
     'First pressing in the textured sleeve.'),
    ('An Ideal for Living', 'Joy Division', 'Rock', 'Enigma', 'PSS 139', 1978, 'EP', 'VG', 'VG', True, '750.00', 1,
     'Self-released 7" EP with the fold-out poster sleeve.'),
    ('Daydream Nation', 'Sonic Youth', 'Rock', 'Blast First', 'BFFP 34', 1988, 'LP', 'VG+', 'VG+', False, '70.00', 2,
     'Double LP.'),
    ('The Beatles Collection', 'The Beatles', 'Rock', 'Parlophone', 'BC 13', 1978, 'box', 'VG+', 'VG', True,
     '600.00', 1, 'Fourteen-LP blue box, all discs VG+ or better.'),
    ('Paranoid', 'Black Sabbath', 'Rock', 'Vertigo', '6360 011', 1970, 'LP', 'VG', 'VG', True, '260.00', 0,
     'Large-swirl label first pressing.'),
    ('Selected Ambient Works 85-92', 'Aphex Twin', 'Electronic', 'Apollo', 'AMB 3922', 1992, 'LP', 'VG+', 'VG+',
     True, '160.00', 1, 'Original double LP.'),
    ('Homework', 'Daft Punk', 'Electronic', 'Virgin', 'V 2821', 1997, 'LP', 'NM', 'NM', False, '42.00', 3, ''),
    ('Blue Monday', 'New Order', 'Electronic', 'Factory', 'FAC 73', 1983, '12in', 'VG+', 'VG+', False, '35.00', 4,
     'Die-cut floppy-disk sleeve.'),
    ('Strings of Life', 'Rhythim Is Rhythim', 'Electronic', 'Transmat', 'MS-02', 1987, '12in', 'VG', 'G+', True,
     '190.00', 1, 'Original Transmat in a generic sleeve.'),
    ('Computer World', 'Kraftwerk', 'Electronic', 'EMI', 'EMC 3370', 1981, 'LP', 'VG+', 'VG+', False, '48.00', 2, ''),
    ('Illmatic', 'Nas', 'Hip-Hop', 'Columbia', 'C 57684', 1994, 'LP', 'VG+', 'VG', True, '220.00', 1,
     'Original 1994 US pressing.'),
    ('3 Feet High and Rising', 'De La Soul', 'Hip-Hop', 'Tommy Boy', 'TBLP 1019', 1989, 'LP', 'VG+', 'VG', False,
     '75.00', 2, ''),
    ('Enter the Wu-Tang (36 Chambers)', 'Wu-Tang Clan', 'Hip-Hop', 'Loud', '07863 66336-1', 1993, 'LP', 'VG', 'VG',
     True, '140.00', 0, ''),
    ('The Low End Theory', 'A Tribe Called Quest', 'Hip-Hop', 'Jive', '1418-1-J', 1991, 'LP', 'NM', 'VG+', False,
     '85.00', 2, ''),
    ('Catch a Fire', 'The Wailers', 'Reggae & Dub', 'Island', 'ILPS 9241', 1973, 'LP', 'VG', 'VG', True, '300.00', 1,
     'The hinged "Zippo lighter" sleeve, hinge intact.'),
    ('Super Ape', 'The Upsetters', 'Reggae & Dub', 'Island', 'ILPS 9417', 1976, 'LP', 'VG+', 'VG', False, '60.00', 2,
     ''),
    ('King Tubby Meets Rockers Uptown', 'Augustus Pablo', 'Reggae & Dub', 'Clocktower', 'LPCT 0052', 1976, 'LP',
     'VG+', 'VG+', False, '45.00', 2, ''),
    ('Too Much Too Young', 'The Specials', 'Reggae & Dub', '2 Tone', 'CHS TT 7', 1980, 'EP', 'VG+', 'VG+', False,
     '14.00', 6, 'Live 7" EP in the picture sleeve.'),
    ('Pink Moon', 'Nick Drake', 'Folk', 'Island', 'ILPS 9184', 1972, 'LP', 'VG+', 'VG+', True, '350.00', 1,
     'UK pink-rim palm-tree labels.'),
    ('Blue', 'Joni Mitchell', 'Folk', 'Reprise', 'MS 2038', 1971, 'LP', 'VG+', 'VG', False, '55.00', 2, ''),
]

DEMO_USERS = [
    # username, superuser?, staff group, description
    ('admin', True, None, 'superuser: everything, including the Django admin'),
    ('stock', False, INVENTORY, 'Inventory staff: record details and stock'),
    ('sales', False, SALES, 'Sales staff: orders and pricing'),
    ('alex', False, None, 'customer with a saved cart and order history'),
    ('jordan', False, None, 'customer with a wishlist and order history'),
]

# Saved carts: (label, catalogue number, format) -> quantity. Paranoid has sold out since alex added it,
# so the cart page shows its stock warning.
CARTS = {
    'alex': [(('Warner Bros.', 'BSK 3010', 'LP'), 1), (('Factory', 'FAC 73', '12in'), 1), (('Vertigo', '6360 011', 'LP'), 1)],
}

# Wishlists: (pressing, price when saved or None for the current price, was it in stock when saved?)
WISHLISTS = {
    'jordan': [
        (('Island', 'ILPS 9184', 'LP'), '395.00', True),     # price dropped since
        (('Columbia', 'C 57684', 'LP'), None, False),        # back in stock since
        (('Columbia', 'CL 1355', 'LP'), None, False),        # still sold out
        (('Westbound', 'WB 2007', 'LP'), None, True),
    ],
    'alex': [
        (('Blue Note', 'BLP 1577', 'LP'), None, True),
    ],
}

# Past orders: (status, days ago, [(pressing, quantity), ...]). Created once per customer.
ORDERS = {
    'alex': [
        (Order.Status.SHIPPED, 21, [(('EMI', 'EMC 3370', 'LP'), 1), (('Virgin', 'V 2821', 'LP'), 1)]),
        (Order.Status.PAID, 5, [(('Tamla', 'TS 310', 'LP'), 1)]),
    ],
    'jordan': [
        (Order.Status.SHIPPED, 12, [(('Factory', 'FAC 73', '12in'), 1), (('Tommy Boy', 'TBLP 1019', 'LP'), 1)]),
        (Order.Status.SHIPPED, 3, [(('2 Tone', 'CHS TT 7', 'EP'), 2)]),
        (Order.Status.CANCELLED, 8, [(('Warner Bros.', 'BSK 3010', 'LP'), 1)]),
        (Order.Status.PENDING, 1, [(('Columbia', 'CS 8171', 'LP'), 1)]),
    ],
}


def find_record(label, catalogue_number, format):
    return Record.objects.select_related('artist').get(
        label__iexact=label, catalogue_key=catalogue_key(catalogue_number), format=format
    )


class Command(BaseCommand):
    """Project-wide demo data, so it is the one core module that knows about the other apps."""

    help = (
        'Create demo accounts (a superuser, Inventory and Sales staff, two customers), a catalogue of about 30 '
        'records, a saved cart, wishlists and past orders. Records are matched by label, catalogue number and '
        'format, so re-running resets them to the demo values without duplicates. Passwords are generated on '
        'every run (or taken from DEMO_PASSWORD in the environment or .env) and printed to the console.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Delete every record, artist and genre first (carts, wishlists and logs go too; orders keep '
                 'their snapshots).',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options['reset']:
            # Records first: artists and genres are protected while records reference them.
            Record.objects.all().delete()
            Artist.objects.all().delete()
            Genre.objects.all().delete()
            self.stdout.write('Removed the existing catalogue.')

        users, credentials = self.create_demo_users()
        self.seed_catalogue(users['admin'])
        self.seed_carts(users)
        self.seed_wishlists(users)
        self.seed_orders(users)

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Demo accounts'))
        for username, password, description in credentials:
            self.stdout.write(f'  {username:<8} {password:<20} ({description})')
        self.stdout.write('These passwords are not stored anywhere else; re-run this command to rotate them.')

    def create_demo_users(self):
        User = get_user_model()
        shared_password = config('DEMO_PASSWORD', default='')
        users, credentials = {}, []
        for username, is_admin, group_name, description in DEMO_USERS:
            password = shared_password or secrets.token_urlsafe(12)
            user, _ = User.objects.get_or_create(
                username=username, defaults={'email': f'{username}@vinylvault.example.com'}
            )
            user.is_superuser = is_admin
            # Staff accounts may open the Django admin, where they also only see what their group allows.
            user.is_staff = is_admin or group_name is not None
            user.set_password(password)
            user.save()
            if group_name:
                # The group comes from the staffdash data migration.
                user.groups.set([Group.objects.get(name=group_name)])
            users[username] = user
            credentials.append((username, password, description))
        return users, credentials

    def seed_catalogue(self, admin):
        artists = {}
        for name, bio in ARTISTS.items():
            artists[name], _ = Artist.objects.update_or_create(name=name, defaults={'bio': bio})

        created = 0
        for (title, artist, genre_name, label, number, year, format, media, sleeve, rare, price, stock,
             notes) in RECORDS:
            genre, _ = Genre.objects.get_or_create(name=genre_name)
            values = {
                'title': title, 'artist': artists[artist], 'genre': genre, 'catalogue_number': number,
                'release_year': year, 'media_grade': media, 'sleeve_grade': sleeve, 'is_rare': rare,
                'price': Decimal(price), 'stock': stock, 'pressing_notes': notes,
            }
            record = Record.objects.filter(label=label, catalogue_key=catalogue_key(number), format=format).first()
            if record is None:
                record = Record(label=label, format=format, **values)
                record.full_clean()
                record.save()
                inventory.log_initial_stock(record, user=admin)
                created += 1
                continue
            # Re-seeding resets the demo values; log any stock or price it puts back.
            if record.stock != stock:
                StockAdjustment.objects.create(
                    record=record, user=admin, change=stock - record.stock, stock_after=stock,
                    reason=StockAdjustment.Reason.CORRECTION, note='Demo data reset',
                )
            if record.price != Decimal(price):
                PriceChange.objects.create(
                    record=record, user=admin, old_price=record.price, new_price=Decimal(price), note='Demo data reset'
                )
            for field, value in values.items():
                setattr(record, field, value)
            record.full_clean()
            record.save()

        self.stdout.write(self.style.SUCCESS(
            f'Catalogue ready: {len(RECORDS)} demo records ({created} new) across '
            f'{Genre.objects.count()} genres and {Artist.objects.count()} artists.'
        ))

    def seed_carts(self, users):
        for username, lines in CARTS.items():
            cart = DatabaseCart(users[username])
            cart.clear()
            for pressing, quantity in lines:
                # Written directly rather than through cart.add(): the demo includes a line that has since sold out.
                cart._store(find_record(*pressing).pk, quantity)
        self.stdout.write(self.style.SUCCESS(
            f'Saved carts ready: {CartItem.objects.filter(cart__user__username__in=CARTS).count()} lines.'
        ))

    def seed_wishlists(self, users):
        count = 0
        for username, entries in WISHLISTS.items():
            for pressing, price_when_added, in_stock_when_added in entries:
                record = find_record(*pressing)
                WishlistItem.objects.update_or_create(
                    user=users[username], record=record,
                    defaults={
                        'price_when_added': Decimal(price_when_added) if price_when_added else record.price,
                        'in_stock_when_added': in_stock_when_added,
                    },
                )
                count += 1
        self.stdout.write(self.style.SUCCESS(f'Wishlists ready: {count} saved records.'))

    def seed_orders(self, users):
        now = timezone.now()
        created = 0
        for username, orders in ORDERS.items():
            user = users[username]
            if user.orders.exists():
                continue
            for status, days_ago, lines in orders:
                placed = now - timedelta(days=days_ago, hours=2)
                items = [snapshot_item(find_record(*pressing), quantity) for pressing, quantity in lines]
                order = Order.objects.create(
                    user=user, status=status, full_name=user.username.title(), email=user.email,
                    shipping_address='1 Groove Street\nDublin 8',
                    total=sum(item.subtotal for item in items),
                )
                for item in items:
                    item.order = order
                OrderItem.objects.bulk_create(items)
                # History, not live sales: backdate the order and leave current stock alone.
                Order.objects.filter(pk=order.pk).update(
                    created_at=placed,
                    paid_at=placed + timedelta(hours=3) if status in Order.SALE_STATUSES else None,
                    shipped_at=placed + timedelta(days=1) if status == Order.Status.SHIPPED else None,
                    cancelled_at=placed + timedelta(hours=5) if status == Order.Status.CANCELLED else None,
                )
                created += 1
        self.stdout.write(self.style.SUCCESS(f'Order history ready: {Order.objects.count()} orders ({created} new).'))
