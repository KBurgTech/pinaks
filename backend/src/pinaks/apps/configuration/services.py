from collections.abc import Mapping

from django.db import transaction

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.services import record_event
from pinaks.apps.configuration.models import FEATURE_FIELDS, CompanyProfile


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
