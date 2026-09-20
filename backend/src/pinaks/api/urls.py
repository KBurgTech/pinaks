from django.urls import URLPattern, path
from drf_spectacular.views import SpectacularJSONAPIView

from pinaks.api.views import api_root, probe

app_name = "api-v1"

urlpatterns: list[URLPattern] = [
    path("", api_root, name="root"),
    path("probe/", probe, name="probe"),
    path("schema/", SpectacularJSONAPIView.as_view(), name="schema"),
]
