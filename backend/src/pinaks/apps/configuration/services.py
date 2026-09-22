from collections.abc import Mapping

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.services import record_event
from pinaks.apps.configuration.models import FEATURE_FIELDS, CompanyProfile, TaxProfile


def get_feature_flags() -> dict[str, bool]:
    profile = CompanyProfile.objects.first()
    if profile is None:
        return dict.fromkeys(FEATURE_FIELDS, False)
    return {code: bool(getattr(profile, field)) for code, field in FEATURE_FIELDS.items()}


@transaction.atomic
def save_company_profile(
    *,
    values: Mapping[str, object],
    actor: User,
    correlation_id: str,
) -> tuple[CompanyProfile, bool]:
    profile = CompanyProfile.objects.select_for_update().first()
    created = profile is None
    if profile is None:
        profile = CompanyProfile()

    features = values.get("features")
    for field, value in values.items():
        if field != "features":
            setattr(profile, field, value)
    if isinstance(features, Mapping):
        for code, value in features.items():
            setattr(profile, FEATURE_FIELDS[str(code)], value)

    profile.full_clean()
    profile.save(force_insert=created)
    record_event(
        actor=actor,
        action_code="configuration.company_changed",
        target_type="configuration.company_profile",
        target_identifier=str(profile.pk),
        correlation_id=correlation_id,
        metadata={"changed_fields": sorted(values)},
    )
    return profile, created


_TAX_PROFILE_VALUE_FIELDS = (
    "name",
    "tax_category",
    "rate",
    "exemption_reason_code",
    "exemption_wording_en",
    "exemption_wording_de",
    "price_entry_policy",
    "tax_column_policy",
    "is_default",
)


def _assign_tax_profile_values(profile: TaxProfile, values: Mapping[str, object]) -> None:
    for field in _TAX_PROFILE_VALUE_FIELDS:
        if field in values:
            setattr(profile, field, values[field])
    if "required_seller_identifiers" in values:
        identifiers = values["required_seller_identifiers"]
        profile.requires_tax_number = isinstance(identifiers, (list, tuple, set, frozenset)) and (
            "tax_number" in identifiers
        )
        profile.requires_vat_identifier = (
            isinstance(identifiers, (list, tuple, set, frozenset))
            and "vat_identifier" in identifiers
        )


def _validate_default_seller_identifiers(profile: TaxProfile) -> None:
    if not profile.is_default:
        return
    company = CompanyProfile.objects.first()
    missing = [
        identifier
        for identifier in profile.required_seller_identifiers
        if company is None or not str(getattr(company, identifier)).strip()
    ]
    if missing:
        raise ValidationError(
            {
                "required_seller_identifiers": (
                    "The company profile is missing required seller identifiers: "
                    + ", ".join(missing)
                    + "."
                )
            }
        )


@transaction.atomic
def save_tax_profile(
    *,
    values: Mapping[str, object],
    actor: User,
    correlation_id: str,
    profile: TaxProfile | None = None,
) -> tuple[TaxProfile, bool]:
    """Create or edit a profile, branching a new version after first use."""
    changed_fields = sorted(values)
    created = profile is None
    if profile is None:
        code = str(values.get("code", ""))
        profile = TaxProfile(code=code)
        _assign_tax_profile_values(profile, values)
    else:
        profile = TaxProfile.objects.select_for_update().get(pk=profile.pk)
        if profile.used_at is not None:
            previous_default = profile.is_default
            previous_values = {
                field: getattr(profile, field) for field in _TAX_PROFILE_VALUE_FIELDS
            }
            previous_values["required_seller_identifiers"] = profile.required_seller_identifiers
            profile.is_current = False
            profile.is_default = False
            profile.save(update_fields=("is_current", "is_default"))
            replacement = TaxProfile(
                code=profile.code,
                version=profile.version + 1,
                is_default=previous_default,
            )
            _assign_tax_profile_values(replacement, previous_values)
            _assign_tax_profile_values(replacement, values)
            profile = replacement
            created = True
        else:
            _assign_tax_profile_values(profile, values)

    if profile.is_default:
        TaxProfile.objects.select_for_update().filter(is_current=True, is_default=True).exclude(
            pk=profile.pk
        ).update(is_default=False)
    profile.full_clean()
    _validate_default_seller_identifiers(profile)
    profile.save(force_insert=profile.pk is None)
    record_event(
        actor=actor,
        action_code="configuration.tax_profile_changed",
        target_type="configuration.tax_profile",
        target_identifier=str(profile.pk),
        correlation_id=correlation_id,
        metadata={
            "changed_fields": changed_fields,
            "code": profile.code,
            "version": profile.version,
        },
    )
    return profile, created


def mark_tax_profile_used(profile: TaxProfile) -> None:
    """Lock profile semantics when a draft first references this version."""
    if profile.used_at is None:
        profile.used_at = timezone.now()
        profile.save(update_fields=("used_at",))
