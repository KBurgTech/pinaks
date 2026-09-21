from django.urls import URLPattern, path
from drf_spectacular.views import SpectacularJSONAPIView

from pinaks.api.views import CompanyProfileView, api_root, capabilities, probe

app_name = "api-v1"

urlpatterns: list[URLPattern] = [
    path("", api_root, name="root"),
    path("capabilities/", capabilities, name="capabilities"),
    path("configuration/company/", CompanyProfileView.as_view(), name="company-profile"),
    path("probe/", probe, name="probe"),
    path("schema/", SpectacularJSONAPIView.as_view(), name="schema"),
]
