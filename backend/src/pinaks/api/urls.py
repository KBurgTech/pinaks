from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularJSONAPIView

from pinaks.api.views import (
    CompanyProfileView,
    TaxProfileDetailView,
    TaxProfileListView,
    api_root,
    capabilities,
    probe,
)
from pinaks.apps.billing.preset_views import PresetArchiveView, PresetDetailView, PresetListView

app_name = "api-v1"

urlpatterns: list[URLPattern | URLResolver] = [
    path("", api_root, name="root"),
    path("capabilities/", capabilities, name="capabilities"),
    path("catalog/", include("pinaks.apps.catalog.urls")),
    path("invoices/", include("pinaks.apps.billing.urls")),
    path("invoice-presets/", PresetListView.as_view(), name="preset-list"),
    path("invoice-presets/<int:preset_id>/", PresetDetailView.as_view(), name="preset-detail"),
    path(
        "invoice-presets/<int:preset_id>/archive/",
        PresetArchiveView.as_view(),
        name="preset-archive",
    ),
    path("custom-fields/", include("pinaks.apps.custom_fields.urls")),
    path("customers/", include("pinaks.apps.customers.urls")),
    path("configuration/company/", CompanyProfileView.as_view(), name="company-profile"),
    path(
        "configuration/tax-profiles/",
        TaxProfileListView.as_view(),
        name="tax-profile-list",
    ),
    path(
        "configuration/tax-profiles/<int:profile_id>/",
        TaxProfileDetailView.as_view(),
        name="tax-profile-detail",
    ),
    path("probe/", probe, name="probe"),
    path("schema/", SpectacularJSONAPIView.as_view(), name="schema"),
]
