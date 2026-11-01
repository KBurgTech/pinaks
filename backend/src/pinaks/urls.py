from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path

from pinaks.apps.accounts.connections import connections_redirect, oidc_callback

urlpatterns: list[URLPattern | URLResolver] = [
    path("admin/", admin.site.urls),
    path("accounts/oidc/<str:provider_id>/login/callback/", oidc_callback),
    path("accounts/3rdparty/", connections_redirect),
    path("accounts/", include("allauth.urls")),
    path("api/v1/", include("pinaks.api.urls")),
]
