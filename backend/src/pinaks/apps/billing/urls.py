from django.urls import URLPattern, path

from pinaks.apps.billing.cancellation_views import CancelInvoiceView
from pinaks.apps.billing.credit_note_views import CreditNoteView
from pinaks.apps.billing.payment_views import MarkPaidView, MarkUnpaidView
from pinaks.apps.billing.preset_views import ApplyPresetView
from pinaks.apps.billing.views import (
    InvoiceDetailView,
    InvoiceListView,
    IssueInvoiceView,
    SensitiveInvoiceFieldsView,
    SensitiveInvoiceLineFieldsView,
)
from pinaks.apps.documents.access_views import InvoiceArtifactView, InvoiceDocumentsView

urlpatterns: list[URLPattern] = [
    path("<int:invoice_id>/credit-notes/", CreditNoteView.as_view(), name="invoice-credit-note"),
    path("<int:invoice_id>/cancel/", CancelInvoiceView.as_view(), name="invoice-cancel"),
    path("<int:invoice_id>/mark-paid/", MarkPaidView.as_view(), name="invoice-mark-paid"),
    path("<int:invoice_id>/mark-unpaid/", MarkUnpaidView.as_view(), name="invoice-mark-unpaid"),
    path("<int:invoice_id>/documents/", InvoiceDocumentsView.as_view(), name="invoice-documents"),
    path(
        "<int:invoice_id>/documents/<str:kind>/",
        InvoiceArtifactView.as_view(),
        name="invoice-artifact",
    ),
    path("", InvoiceListView.as_view(), name="invoice-list"),
    path("<int:invoice_id>/", InvoiceDetailView.as_view(), name="invoice-detail"),
    path("<int:invoice_id>/issue/", IssueInvoiceView.as_view(), name="invoice-issue"),
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
