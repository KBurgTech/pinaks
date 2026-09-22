from django.urls import URLPattern, path

from pinaks.apps.catalog.views import (
    CatalogItemDetailView,
    CatalogItemListView,
    SensitiveCatalogItemFieldsView,
)

urlpatterns: list[URLPattern] = [
    path(
        "<int:item_id>/sensitive-fields/",
        SensitiveCatalogItemFieldsView.as_view(),
        name="catalog_item-sensitive-fields",
    ),
    path("", CatalogItemListView.as_view(), name="catalog-item-list"),
    path("<int:item_id>/", CatalogItemDetailView.as_view(), name="catalog-item-detail"),
]
