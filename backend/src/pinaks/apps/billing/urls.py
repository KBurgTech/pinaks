from django.urls import URLPattern, path

from pinaks.apps.billing.preset_views import ApplyPresetView
from pinaks.apps.billing.views import (
    InvoiceDetailView,
    InvoiceListView,
    SensitiveInvoiceFieldsView,
    SensitiveInvoiceLineFieldsView,
)

urlpatterns: list[URLPattern] = [
    path("", InvoiceListView.as_view(), name="invoice-list"),
    path("<int:invoice_id>/", InvoiceDetailView.as_view(), name="invoice-detail"),
    path(
        "<int:invoice_id>/sensitive-fields/",
        SensitiveInvoiceFieldsView.as_view(),
        name="invoice-sensitive-fields",
    ),
    path(
        "<int:invoice_id>/lines/<int:line_id>/sensitive-fields/",
        SensitiveInvoiceLineFieldsView.as_view(),
        name="invoice-line-sensitive-fields",
    ),
    path("<int:invoice_id>/apply-preset/", ApplyPresetView.as_view(), name="invoice-apply-preset"),
]
