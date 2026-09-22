import dj_database_url

from .base import *  # noqa: F403

SECRET_KEY = "test-only-not-a-secret"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DATABASES = {"default": dj_database_url.config(default="sqlite:///:memory:", conn_max_age=0)}
