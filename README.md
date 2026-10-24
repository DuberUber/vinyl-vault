# Vinyl Vault

**Vinyl Vault | Python, Django, SQLite, Bootstrap**: an online record shop. Customers browse rare and
collectable vinyl, save records to a wishlist and check out with a cart that follows them between devices.
Staff manage stock and pricing from role-based dashboards built on Django's auth groups and permissions.

**Stack:** Python 3.10+ · Django 5.2 LTS · SQLite · Bootstrap 5 with a custom theme · python-decouple

## Features

- **Records.** Every record is a specific pressing with a title, artist, genre, label, catalogue number,
  release year and format (LP, 12" single, 7" single, EP or box set). It carries separate Goldmine grades for
  the vinyl and the sleeve (M, NM, VG+, VG, G+, G), pressing notes, a *rare* flag, a price and a stock count.
  Catalogue numbers are normalised, and a label, catalogue number and format together identify one record,
  so `BLP 4003`, `blp-4003` and `BLP4003` on Blue Note LP are the same pressing.
- **Search.** One `Q` object (`catalog/search.py`) covers:
  - text matched against title, artist, label and catalogue number (catalogue numbers ignore spaces and
    hyphens);
  - filters for genre, format, minimum vinyl grade, a price range, rare only and in stock only;
  - sorting by title, artist, price, release year or date added.

  Filters survive pagination, and the same search is available as JSON at `/records/api/`.
- **Saved carts.**
  - Guests keep a cart in their session. A signed-in customer's cart is stored in the database, so it's still
    there on another device or after logging out.
  - When a guest logs in or signs up, their session cart merges into their saved cart. Quantities add
    together, capped at the stock available, with a message for anything that couldn't be merged in full.
  - Stock is checked whenever something is added. If stock later drops below what's in a cart, the cart flags
    the line and blocks checkout until it's fixed.
- **Checkout.** Runs in one transaction:
  - the cart's records are locked with `select_for_update()` and stock is re-checked *after* locking;
  - only then does it create the order, snapshot each line and decrement stock.

  Any problem rolls the whole thing back, so there are never partial updates. Order lines snapshot the
  title, artist, format, condition and price, so later catalogue edits (or deleting the record) never change
  past orders.
- **Orders.** Statuses run *pending → paid → shipped*, or *cancelled*. Customers can cancel until they've
  paid; the sales team can also cancel paid orders. Cancelling puts the records back in stock.
- **Wishlist.** A heart button on every record saves it, remembering the price and whether it was in stock at
  the time. *My wishlist* flags records that are **back in stock** or have **dropped in price**, the
  navigation shows a dot when there's news, and *Move to cart* takes a record straight to the cart.
- **Staff dashboards** at `/staff/`, with access set by group (see below):
  - **Overview:** low stock, recent orders, the most-wishlisted records, and 30-day sales (revenue, orders,
    units, average order, a daily chart, best sellers), all computed with database aggregates.
  - **Inventory:** add and edit records. Each stock change (delivery, stock-take correction, damage) is logged
    with who made it and why.
  - **Pricing:** change one price, or raise or cut prices by a percentage across a genre and/or format.
    Every change is logged, and the records in a bulk change share a batch id.
  - **Orders:** mark orders paid or shipped, or cancel and restock them.
- **Audit trail.** Sales at checkout and restocks from cancellations go into the same stock log as manual
  adjustments, so a record's stock history is always complete.
- **Accounts.** Sign-up with Django's password validators and unique emails, log in/out, a profile page and
  password change.
- **Look and feel.** A record-shop theme: a charcoal "listening booth" header and footer, warm sleeve-card
  surfaces, label-red actions, mustard highlights and Space Grotesk headings. Each record gets a generated
  sleeve tinted from its title, with a disc that slides out on hover. The layout works down to phone widths.

## Staff roles

The `Inventory` and `Sales` groups are created, with their permissions, by a data migration
(`staffdash/migrations/0001_staff_groups.py`), so every fresh database has them. Staff views use
`PermissionRequiredMixin`: anonymous visitors are sent to log in, and signed-in users without the permission
get a **403**. `is_staff` alone opens nothing.

| Area | Permission | Inventory | Sales |
| --- | --- | :---: | :---: |
| Overview (`/staff/`) | any one of the permissions below | ✓ | ✓ |
| Inventory list, edit records | `catalog.change_record` | ✓ | |
| Add records | `catalog.add_record` | ✓ | |
| Adjust stock | `catalog.adjust_stock` | ✓ | |
| Stock log | `catalog.view_stockadjustment` | ✓ | |
| Single and bulk price changes | `catalog.change_price` | | ✓ |
| Price log | `catalog.view_pricechange` | | ✓ |
| Order list and detail | `orders.view_order` | | ✓ |
| Mark paid/shipped, cancel and restock | `orders.manage_orders` | | ✓ |

Superusers can do everything.

## Architecture

The project is a set of focused Django apps. Each app owns its models, views, templates and tests, and has
its own `urls.py` with an `app_name`, so every link is namespaced (`catalog:record_detail`,
`orders:checkout`, `staffdash:pricing`).

```
.
├── vinylvault/   Project package: settings (python-decouple), root URLconf, WSGI/ASGI
├── core/         Shared layer: base template and theme, error pages, form and permission mixins,
│                 template filters, /health/ check, test factories, seed_demo_data command
├── accounts/     Sign up, log in/out, profile, password change
├── catalog/      Genre, Artist, Record, StockAdjustment and PriceChange models; search.py (one Q object);
│                 services.py (locked, logged stock and price changes); shop pages and JSON search
├── orders/       Cart, CartItem, Order and OrderItem; cart.py (session and saved carts, merge on login);
│                 services.py (checkout, status changes, cancel and restock); cart, checkout, history
├── wishlist/     WishlistItem; heart toggle, My wishlist, move to cart
├── staffdash/    Staff groups (data migration) and role-based dashboards for inventory, pricing and orders
├── manage.py
├── requirements.txt
└── .env.example
```

| URL prefix | App | Main pages |
| --- | --- | --- |
| `/` | catalog | Home, `records/` (search), `records/<id>/`, `records/api/`, `genres/<slug>/`, `artists/<id>/` |
| `/orders/` | orders | `cart/`, `checkout/`, order history, `<id>/`, `<id>/cancel/` |
| `/wishlist/` | wishlist | My wishlist, `toggle/<record id>/`, `<record id>/move-to-cart/` |
| `/staff/` | staffdash | Overview, `inventory/`, `pricing/`, `orders/` and their logs |
| `/accounts/` | accounts | `signup/`, `login/`, `logout/`, `profile/`, `password/` |
| `/admin/` | Django admin | Everything, for superusers |
| `/health/` | core | JSON health check (also pings the database) |

### Data model

```
Artist 1 ── * Record * ── 1 Genre
Record 1 ── * StockAdjustment   (change, stock after, reason, user, note)
Record 1 ── * PriceChange       (old/new price, bulk percent and batch, user, note)
User 1 ── 1 Cart 1 ── * CartItem * ── 1 Record
User 1 ── * WishlistItem * ── 1 Record   (price and availability when saved)
User 1 ── * Order 1 ── * OrderItem       (title, artist, format, condition and price snapshot;
                                          record set to NULL if it's deleted)
```

Constraints enforced in the database:

- One record per pressing: case-insensitive label + normalised catalogue number + format.
- One cart line and one wishlist entry per record per user.
- Artist and genre deletes are blocked while records use them (`PROTECT`); orders keep their history if a
  record is deleted (`SET_NULL`).

### How the apps stay decoupled

- **Dependencies point one way.** `orders`, `wishlist` and `staffdash` depend on `catalog`, never the
  reverse. Cart and order lines point at records through foreign keys without reverse accessors, so the
  catalogue knows nothing about carts or orders.
- **Business rules live in service modules.** Views, staff dashboards and admin actions call
  `catalog/services.py`, `orders/cart.py`, `orders/services.py` and `wishlist/services.py` instead of
  changing rows directly. Locking, logging and status rules live in one place and are unit tested.
- **Shared code lives in `core`**, which imports no other project app. The exceptions are the base template,
  which links to every app, and the project-wide `seed_demo_data` command.

### Concurrency on SQLite

SQLite has no row locks, so Django leaves out `FOR UPDATE` there. The database is configured with
`"transaction_mode": "IMMEDIATE"`, so every transaction takes SQLite's write lock as soon as it starts.
Checkouts and stock changes then run one after another, and the second one sees the first one's committed
stock. The code still calls `select_for_update()` and re-reads stock after locking, so it stays correct on a
database with row locks too.

## Getting started

### Prerequisites

- Python 3.10 or newer

### 1. Install and configure

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env
```

Set `SECRET_KEY` in `.env`. You can generate one with:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 2. Create the database and start the server

```bash
python manage.py migrate             # also creates the Inventory and Sales groups
python manage.py seed_demo_data      # prints the demo passwords, so note them
python manage.py test                # optional: should end with OK
python manage.py runserver
```

Open http://127.0.0.1:8000/ for the shop, http://127.0.0.1:8000/staff/ for the staff dashboards and
http://127.0.0.1:8000/admin/ for the Django admin. If port 8000 is taken, run
`python manage.py runserver 8001` instead.

`seed_demo_data` creates five accounts:

| Account | Role | Demo data |
| --- | --- | --- |
| `admin` | Superuser | Everything, including the Django admin |
| `stock` | Inventory group | Record details and stock |
| `sales` | Sales group | Orders and pricing |
| `alex` | Customer | A saved cart (one line has since sold out, so the cart shows its warning), a wishlist, a shipped and a paid order |
| `jordan` | Customer | A wishlist with a price drop and a back-in-stock record; shipped, pending and cancelled orders |

It also loads 35 records across 7 genres and every format, including rare pressings and sold-out records.
Passwords are generated on each run and **printed only to your console**, so no credentials live in the
repository. Set `DEMO_PASSWORD` in `.env` to use a fixed password instead. Running the command again rotates
the passwords and resets the demo records' stock and prices, logging the reset, without creating
duplicates. Pass `--reset` to wipe and rebuild the catalogue.

### 3. Try it out

- **Search:** search for `blp-4003` or `jazz`, then try *Rare finds only*, a format and *Vinyl grade at least VG+*.
- **Saved cart:** as a guest, add a record to the cart, then log in as `alex`. The guest cart merges into
  alex's saved cart, which also flags the sold-out *Paranoid*. Remove it, then check out.
- **Wishlist:** log in as `jordan` and open **Wishlist**: *Pink Moon* shows a price drop and *Illmatic* is
  back in stock. Move one to the cart.
- **Inventory:** log in as `stock`, open **Staff → Inventory**, record a delivery, then check the stock log.
  Try **Pricing**: you'll get a 403.
- **Sales:** log in as `sales`, mark alex's paid order as shipped, cancel jordan's pending order (its stock
  goes back up), and cut all Electronic 12" singles by 10% under **Pricing**.
- **JSON search:** open http://127.0.0.1:8000/records/api/?q=blue+note&rare=on

### Stopping and restarting

- Stop the server with `Ctrl+C`; leave the virtualenv with `deactivate`.
- Next time, activate the virtualenv and run `python manage.py runserver` from the project root.
- To start over, delete `db.sqlite3`, then run `python manage.py migrate` and `python manage.py seed_demo_data`.
- Lost the demo passwords? Run `python manage.py seed_demo_data` again; each run replaces them.

### Troubleshooting

| Problem | Fix |
| --- | --- |
| `SECRET_KEY not found` | `.env` is missing. Copy `.env.example` to `.env` and set `SECRET_KEY`. |
| "Please enter a correct username and password" | Use the passwords from your most recent `seed_demo_data` run. |
| `Error: That port is already in use` | Stop the other server, or run `python manage.py runserver 8001`. |
| Staff pages return 403 | Log in as `stock`, `sales` or `admin`; customers can't open them. |
| Pages look unstyled | Bootstrap and the fonts load from CDNs, so check your internet connection. With `DEBUG=False`, run `collectstatic` and serve `staticfiles/`. |

## Search parameters

The record search (`/records/`) and the JSON endpoint (`/records/api/`) accept the same query parameters:

| Parameter | Example | Effect |
| --- | --- | --- |
| `q` | `q=coltrane` | Case-insensitive match on title, artist, label or catalogue number (spaces and hyphens ignored in catalogue numbers) |
| `genre` | `genre=3` | Genre ID |
| `format` | `format=LP&format=12in` | Any of `LP`, `12in`, `7in`, `EP`, `box` |
| `condition` | `condition=VG%2B` | Minimum vinyl grade: `M`, `NM`, `VG+`, `VG`, `G+` or `G` |
| `min_price`, `max_price` | `min_price=20&max_price=100` | Price range, inclusive |
| `rare` | `rare=on` | Only records flagged as rare |
| `in_stock` | `in_stock=on` | Only records with copies left |
| `sort` | `sort=-price` | `title` (default), `artist`, `price`, `-price`, `year`, `-year`, `newest` |
| `page` | `page=2` | 12 results per page |

Invalid values are shown as form errors and left out of the query; the JSON endpoint returns `400` with
field errors instead.

```bash
curl "http://127.0.0.1:8000/records/api/?q=blue%20note&format=LP&condition=VG%2B&sort=-price"
```

## Configuration

Settings are read from environment variables or `.env` via python-decouple, and nothing secret is
hard-coded.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | *(required)* | Django secret key |
| `DEBUG` | `False` | Development mode |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost` | Comma-separated host names |
| `CSRF_TRUSTED_ORIGINS` | *(empty)* | HTTPS origins allowed to submit forms |
| `SQLITE_PATH` | `db.sqlite3` next to `manage.py` | Location of the SQLite database |
| `DEMO_PASSWORD` | *(random)* | Fixed password for the `seed_demo_data` accounts |
| `CURRENCY_SYMBOL` | `€` | Symbol used when displaying prices |
| `LOW_STOCK_THRESHOLD` | `2` | Stock level at or below which the dashboard flags a record |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | `False`, `0` | HTTPS hardening (applies when `DEBUG=False`) |

## Tests

```bash
python manage.py test
```

The suite of 180 tests covers:

- **Search:** the combined `Q` object, each filter, catalogue-number matching, sorting, validation,
  pagination and the JSON API.
- **Records:** catalogue-number normalisation and the one-record-per-pressing constraint.
- **Carts:** session and saved carts, merging on login and sign-up (including stock caps), stock limits on
  add and update, and the warning when stock drops.
- **Checkout:**
  - the last copy going to whoever checks out first;
  - stock read after locking, with `select_for_update` in use;
  - a mid-checkout failure rolling everything back;
  - order snapshots surviving catalogue edits and deletion.
- **Orders:** status transitions, customer and staff cancellation with restock, and admin actions.
- **Wishlist:** heart toggle (form and JSON), price-drop and back-in-stock badges, move to cart.
- **Staff:** the data-migration groups, a full page-by-role permission matrix with 403s, dashboard
  aggregates, and the stock and price logs.
- **Accounts, shared utilities and the seed command:** idempotent re-runs, printed passwords and `--reset`.

## Deploying

- Set `DEBUG=False`, a strong `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and the HTTPS settings.
- Run `python manage.py migrate` and `python manage.py collectstatic`, then serve the project with a WSGI
  server such as gunicorn behind an HTTPS reverse proxy. Keep the SQLite file on persistent storage and back
  it up.
- Use `/health/` for load-balancer or uptime checks.
