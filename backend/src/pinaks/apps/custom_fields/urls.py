from django.urls import URLPattern, path

from pinaks.apps.custom_fields.views import DefinitionDetailView, DefinitionListView

urlpatterns: list[URLPattern] = [
    path("", DefinitionListView.as_view(), name="custom-field-definition-list"),
    path("<int:field_id>/", DefinitionDetailView.as_view(), name="custom-field-definition-detail"),
]
