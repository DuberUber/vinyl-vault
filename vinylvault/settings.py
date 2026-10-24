"""
Django settings for the Vinyl Vault record shop.

Environment-specific values (secret key, debug flag, hosts) are read from the environment
or a .env file in the project root via python-decouple; nothing secret is hard-coded here.
See .env.example.

https://docs.djangoproject.com/en/5.2/ref/settings/
"""

from pathlib import Path

from decouple import Csv, config
from django.contrib.messages import constants as messages

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Security
# https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

SECRET_KEY = config("SECRET_KEY")

DEBUG = config("DEBUG", default=False, cast=bool)

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost", cast=Csv())

CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Enable once the site is served over HTTPS (behind a proxy that sets X-Forwarded-Proto).
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0, cast=int)


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Project apps
    "core",
    "accounts",
    "catalog",
    "orders",
    "wishlist",
    "staffdash",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "vinylvault.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "catalog.context_processors.genres",
                "orders.context_processors.cart_summary",
                "wishlist.context_processors.wishlist_summary",
                "staffdash.context_processors.staff_access",
            ],
        },
    },
]

WSGI_APPLICATION = "vinylvault.wsgi.application"


# Database: SQLite, stored next to manage.py.
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases
# SQLite ignores SELECT ... FOR UPDATE, so transactions start IMMEDIATE: each one takes the write
# lock up front, which serialises checkouts and stock changes instead of failing halfway through.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": config("SQLITE_PATH", default=str(BASE_DIR / "db.sqlite3")),
        "OPTIONS": {
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
        },
    },
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"


# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# -------------------------------
# Authentication redirect settings
# -------------------------------

# Where @login_required redirects to
LOGIN_URL = "accounts:login"

# Where to go after successful login
LOGIN_REDIRECT_URL = "/"

# Where to go after logout
LOGOUT_REDIRECT_URL = "/"


# -------------------------------
# Presentation and shop rules
# -------------------------------

# Bootstrap calls the error style "danger".
MESSAGE_TAGS = {messages.ERROR: "danger"}

CURRENCY_SYMBOL = config("CURRENCY_SYMBOL", default="€")

# Records at or below this many copies show up as "low stock" on the staff dashboard.
LOW_STOCK_THRESHOLD = config("LOW_STOCK_THRESHOLD", default=2, cast=int)
