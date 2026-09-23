from django.urls import URLPattern, path

from pinaks.apps.billing.preset_views import ApplyPresetView
from pinaks.apps.billing.views import InvoiceDetailView, InvoiceListView

urlpatterns: list[URLPattern] = [
    path("", InvoiceListView.as_view(), name="invoice-list"),
    path("<int:invoice_id>/", InvoiceDetailView.as_view(), name="invoice-detail"),
    path("<int:invoice_id>/apply-preset/", ApplyPresetView.as_view(), name="invoice-apply-preset"),
]
