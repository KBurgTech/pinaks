import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parents[3]
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "development-only-change-me")
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "pinaks.apps.accounts",
    "pinaks.apps.audit",
    "pinaks.apps.billing",
    "pinaks.apps.catalog",
    "pinaks.apps.configuration",
    "pinaks.apps.custom_fields",
    "pinaks.apps.customers",
    "pinaks.apps.documents",
    "django.contrib.admin",
    "django.contrib.postgres",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "rest_framework",
    "drf_spectacular",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "pinaks.urls"
WSGI_APPLICATION = "pinaks.wsgi.application"
ASGI_APPLICATION = "pinaks.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {
    "default": dj_database_url.config(
        default="postgresql://pinaks:pinaks@localhost:5432/pinaks",
        conn_max_age=60,
        conn_health_checks=True,
    )
}

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("de", "Deutsch")]
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Europe/Berlin")
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / "locale"]
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
ACCOUNT_LOGIN_METHODS = {"username", "email"}
ACCOUNT_ADAPTER = "pinaks.apps.accounts.adapters.AccountAdapter"
ACCOUNT_SIGNUP_FIELDS = ["username*", "email*", "password1*", "password2*"]
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = False
ACCOUNT_LOGOUT_ON_GET = False
LOGIN_REDIRECT_URL = "/app/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/accounts/login/"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "pinaks.api.pagination.StandardPageNumberPagination",
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "EXCEPTION_HANDLER": "pinaks.api.exceptions.api_exception_handler",
    "ORDERING_PARAM": "ordering",
    "PAGE_SIZE": 50,
    "SEARCH_PARAM": "search",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Pinaks API",
    "VERSION": "0.1.0",
    "ENUM_NAME_OVERRIDES": {
        "DocumentLanguage": ["en", "de"],
    },
    "COMPONENT_SPLIT_REQUEST": True,
    "SERVE_INCLUDE_SCHEMA": False,
}
