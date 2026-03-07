"""
Django base settings.
"""
import os
from pathlib import Path
from urllib.parse import urlparse

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    SECRET_KEY=(str, "change-me-in-production"),
    DATABASE_URL=(str, ""),
    CORS_ALLOWED_ORIGINS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    BASE_URL=(str, "http://localhost:8000"),
    LANGUAGE_CODE=(str, "tr-tr"),
    TIME_ZONE=(str, "Europe/Istanbul"),
)
_env_file = os.path.join(BASE_DIR, ".env")
if os.path.exists(_env_file):
    env.read_env(_env_file)

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
_raw_hosts = env.list("ALLOWED_HOSTS")
ALLOWED_HOSTS = _raw_hosts if _raw_hosts else ["localhost", "127.0.0.1"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "whitenoise.runserver_nostatic",
    "corsheaders",
    "config",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.base_url",
            ],
        },
    },
]

DATABASES = {}
_db_url = (env("DATABASE_URL") or "").strip()
if _db_url and not _db_url.startswith("sqlite"):
    DATABASES["default"] = env.db("DATABASE_URL")
elif _db_url and _db_url.startswith("sqlite"):
    # sqlite:///path/to/db.sqlite3 - env.db() host uyarısı vermesin diye elle ayarla
    parsed = urlparse(_db_url)
    path = (parsed.path or "").lstrip("/")
    if path and os.path.isabs(path):
        name = path
    else:
        name = str(BASE_DIR / (path or "db.sqlite3"))
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": name,
    }
else:
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = env("LANGUAGE_CODE")
TIME_ZONE = env("TIME_ZONE")
USE_I18N = True
USE_TZ = True

# Tüm absolute URL'ler için (e-posta, redirect, API vb.)
BASE_URL = env("BASE_URL").rstrip("/")

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS")

# Transkript cache backend
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "OPTIONS": {"MAX_ENTRIES": 1000},
    }
}
# Transkript cache (YouTube’a tekrar istek atmamak için, 1 saat)
TRANSCRIPT_CACHE_TIMEOUT = 3600
TRANSCRIPT_CACHE_KEY_PREFIX = "yt_transcript:"
# API rate limit: dakikada en fazla istek (IP başına)
TRANSCRIPT_RATE_LIMIT_PER_MINUTE = 10

# Transkript: sadece ScrapingBee (Docker: env_file: .env ile SCRAPINGBEE_API_KEY gelir)
SCRAPINGBEE_API_KEY = (os.environ.get("SCRAPINGBEE_API_KEY") or "").strip() or None
# Premium proxy: zor siteler (YouTube) için önerilir; production'da True yapılabilir
SCRAPINGBEE_PREMIUM_PROXY = env.bool("SCRAPINGBEE_PREMIUM_PROXY", default=False)
# İstek timeout (ms); doküman default 140000
SCRAPINGBEE_TIMEOUT = env.int("SCRAPINGBEE_TIMEOUT", default=60000)
