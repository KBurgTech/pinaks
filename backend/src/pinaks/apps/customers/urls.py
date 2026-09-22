from django.urls import URLPattern, path

from pinaks.apps.customers.views import (
    BillingRecipientDetailView,
    BillingRecipientListView,
    CustomerDetailView,
    CustomerListView,
)

urlpatterns: list[URLPattern] = [
    path("", CustomerListView.as_view(), name="customer-list"),
    path("<int:customer_id>/", CustomerDetailView.as_view(), name="customer-detail"),
    path(
        "<int:customer_id>/billing-recipients/",
        BillingRecipientListView.as_view(),
        name="billing-recipient-list",
    ),
    path(
        "<int:customer_id>/billing-recipients/<int:recipient_id>/",
        BillingRecipientDetailView.as_view(),
        name="billing-recipient-detail",
    ),
]
