from django.urls import URLPattern, path

from pinaks.apps.catalog.views import CatalogItemDetailView, CatalogItemListView

urlpatterns: list[URLPattern] = [
    path("", CatalogItemListView.as_view(), name="catalog-item-list"),
    path("<int:item_id>/", CatalogItemDetailView.as_view(), name="catalog-item-detail"),
]
