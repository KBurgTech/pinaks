from collections.abc import Mapping

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.services import record_event
from pinaks.apps.catalog.models import CatalogItem
from pinaks.apps.configuration.models import TaxProfile
from pinaks.apps.custom_fields.services import validate_custom_data

_CATALOG_FIELDS = (
    "code",
    "description_en",
    "description_de",
    "unit",
    "default_price",
    "minimum_price",
    "maximum_price",
)


class CatalogCodeImmutableError(ValueError):
    pass


def _assign_values(item: CatalogItem, values: Mapping[str, object]) -> None:
    for field in _CATALOG_FIELDS:
        if field in values:
            setattr(item, field, values[field])
    if "default_tax_profile_id" in values:
        tax_profile_id = values["default_tax_profile_id"]
        if not isinstance(tax_profile_id, int) or isinstance(tax_profile_id, bool):
            raise ValidationError({"default_tax_profile_id": "Enter a valid integer."})
        item.default_tax_profile_id = tax_profile_id


def _validate_current_tax_profile(item: CatalogItem) -> None:
    if not TaxProfile.objects.filter(pk=item.default_tax_profile_id, is_current=True).exists():
        raise ValidationError({"default_tax_profile_id": "Select a current supported tax profile."})


@transaction.atomic
def create_catalog_item(
    *, values: Mapping[str, object], actor: User, correlation_id: str
) -> CatalogItem:
    item = CatalogItem()
    _assign_values(item, values)
    _validate_current_tax_profile(item)
    item.custom_data = validate_custom_data(
        target="catalog_item", values=values.get("custom_data", {}), existing=item.custom_data
    )
    item.full_clean()
    item.save(force_insert=True)
    record_event(
        actor=actor,
        action_code="catalog.item_created",
        target_type="catalog.catalog_item",
        target_identifier=str(item.pk),
        correlation_id=correlation_id,
        metadata={"changed_fields": sorted(values), "code": item.code},
    )
    return item


@transaction.atomic
def update_catalog_item(
    *, item: CatalogItem, values: Mapping[str, object], actor: User, correlation_id: str
) -> CatalogItem:
    item = CatalogItem.objects.select_for_update().get(pk=item.pk)
    if "code" in values and values["code"] != item.code:
        raise CatalogCodeImmutableError("The catalog code cannot be changed.")
    _assign_values(item, values)
    _validate_current_tax_profile(item)
    item.custom_data = validate_custom_data(
        target="catalog_item", values=values.get("custom_data", {}), existing=item.custom_data
    )
    item.full_clean()
    item.save()
    record_event(
        actor=actor,
        action_code="catalog.item_updated",
        target_type="catalog.catalog_item",
        target_identifier=str(item.pk),
        correlation_id=correlation_id,
        metadata={"changed_fields": sorted(values), "code": item.code},
    )
    return item


@transaction.atomic
def archive_catalog_item(*, item: CatalogItem, actor: User, correlation_id: str) -> CatalogItem:
    item = CatalogItem.objects.select_for_update().get(pk=item.pk)
    if not item.is_archived:
        item.is_archived = True
        item.save(update_fields=("is_archived", "modified_at"))
        record_event(
            actor=actor,
            action_code="catalog.item_archived",
            target_type="catalog.catalog_item",
            target_identifier=str(item.pk),
            correlation_id=correlation_id,
            metadata={"code": item.code},
        )
    return item


def search_catalog_items(*, search: str = "", archived: bool = False) -> QuerySet[CatalogItem]:
    items = CatalogItem.objects.filter(is_archived=archived).select_related("default_tax_profile")
    if search:
        items = items.filter(
            Q(code__icontains=search)
            | Q(description_en__icontains=search)
            | Q(description_de__icontains=search)
        )
    return items.order_by("code")


def draft_line_defaults(*, item_id: int, language: str) -> dict[str, object]:
    """Return copied catalog and tax values for a new invoice line."""
    item = CatalogItem.objects.select_related("default_tax_profile").get(
        pk=item_id, is_archived=False
    )
    profile = item.default_tax_profile
    if not profile.is_current:
        raise ValidationError({"catalog_item_id": "Select an item with a current tax profile."})
    return {
        "item_code": item.code,
        "description": item.description_de if language == "de" else item.description_en,
        "unit": item.unit,
        "unit_price": item.default_price,
        "tax_category": profile.tax_category,
        "tax_rate": profile.rate,
        "price_entry_policy": profile.price_entry_policy,
        "exemption_reason_code": profile.exemption_reason_code,
        "exemption_wording": profile.exemption_wording_de
        if language == "de"
        else profile.exemption_wording_en,
    }
