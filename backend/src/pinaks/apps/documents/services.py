import re
from collections.abc import Mapping
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.services import record_event
from pinaks.apps.documents.models import (
    DocumentAsset,
    DocumentTemplate,
    DocumentTemplateVersion,
    VersionStatus,
)

MAX_ASSET_BYTES = 2 * 1024 * 1024
ASSET_SIGNATURES = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}
_UNSAFE_REFERENCE = re.compile(r"(?:https?://|file:|(?:src|href)\s*=\s*['\"]\s*/)", re.I)


@transaction.atomic
def create_template(*, code: str, name: str, actor: User, correlation_id: str) -> DocumentTemplate:
    template = DocumentTemplate(code=code, name=name)
    template.full_clean()
    template.save()
    record_event(
        actor=actor,
        action_code="documents.template_created",
        target_type="documents.template",
        target_identifier=str(template.pk),
        correlation_id=correlation_id,
        metadata={"code": template.code},
    )
    return template


def _apply_version_values(version: DocumentTemplateVersion, values: Mapping[str, object]) -> None:
    for field in ("html", "css", "page_settings", "asset_keys"):
        if field in values:
            setattr(version, field, values[field])
    if _UNSAFE_REFERENCE.search(version.html) or _UNSAFE_REFERENCE.search(version.css):
        raise ValidationError({"html": "Remote and absolute references are not allowed."})
    settings = version.page_settings
    if not isinstance(settings, dict) or settings.get("size") != "A4" or set(settings) != {"size"}:
        raise ValidationError({"page_settings": "Only A4 page size is supported."})
    keys = version.asset_keys
    if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
        raise ValidationError({"asset_keys": "Asset keys must be a list of stored keys."})
    if len(keys) != len(set(keys)) or DocumentAsset.objects.filter(
        template=version.template, key__in=keys
    ).count() != len(keys):
        raise ValidationError({"asset_keys": "Unknown or duplicate asset key."})


@transaction.atomic
def save_version(
    *,
    template_id: int,
    values: Mapping[str, object],
    actor: User,
    correlation_id: str,
    version_id: int | None = None,
) -> DocumentTemplateVersion:
    template = DocumentTemplate.objects.select_for_update().get(pk=template_id)
    if version_id is None:
        language = str(values["language"])
        if DocumentTemplateVersion.objects.filter(
            template=template, language=language, status=VersionStatus.DRAFT
        ).exists():
            raise ValidationError({"language": "Edit the existing draft before creating another."})
        last = (
            DocumentTemplateVersion.objects.filter(template=template, language=language)
            .order_by("-version")
            .first()
        )
        version = DocumentTemplateVersion(
            template=template,
            language=language,
            version=1 if last is None else last.version + 1,
            created_by=actor,
        )
    else:
        source = DocumentTemplateVersion.objects.select_for_update().get(
            pk=version_id, template=template
        )
        if source.status == VersionStatus.PUBLISHED:
            existing = DocumentTemplateVersion.objects.filter(
                template=template, language=source.language, status=VersionStatus.DRAFT
            ).first()
            if existing is not None:
                version = existing
            else:
                last_number = (
                    DocumentTemplateVersion.objects.filter(
                        template=template, language=source.language
                    )
                    .order_by("-version")
                    .values_list("version", flat=True)
                    .first()
                )
                version = DocumentTemplateVersion(
                    template=template,
                    language=source.language,
                    version=(last_number or 0) + 1,
                    html=source.html,
                    css=source.css,
                    page_settings=source.page_settings,
                    asset_keys=source.asset_keys,
                    created_by=actor,
                )
        else:
            version = source
    _apply_version_values(version, values)
    version.full_clean()
    version.save()
    record_event(
        actor=actor,
        action_code="documents.template_draft_saved",
        target_type="documents.template_version",
        target_identifier=str(version.pk),
        correlation_id=correlation_id,
        metadata={
            "template_id": template.pk,
            "language": version.language,
            "version": version.version,
        },
    )
    return version


@transaction.atomic
def publish_template(*, template_id: int, actor: User, correlation_id: str) -> DocumentTemplate:
    template = DocumentTemplate.objects.select_for_update().get(pk=template_id)
    versions = list(DocumentTemplateVersion.objects.filter(template=template).order_by("-version"))
    selected: dict[str, DocumentTemplateVersion] = {}
    for language in ("en", "de"):
        selected_version = next((v for v in versions if v.language == language), None)
        if selected_version is None or not selected_version.html.strip():
            raise IncompleteTranslationsError("Complete English and German versions are required.")
        selected[language] = selected_version
    drafts = [version for version in selected.values() if version.status == VersionStatus.DRAFT]
    if not drafts:
        raise IncompleteTranslationsError("No draft versions are ready to publish.")
    now = timezone.now()
    for version in drafts:
        version.status = VersionStatus.PUBLISHED
        version.published_by = actor
        version.published_at = now
        version.save(update_fields=("status", "published_by", "published_at"))
    record_event(
        actor=actor,
        action_code="documents.template_published",
        target_type="documents.template",
        target_identifier=str(template.pk),
        correlation_id=correlation_id,
        metadata={
            "languages": sorted(selected),
            "versions": {k: v.version for k, v in selected.items()},
        },
    )
    return template


class IncompleteTranslationsError(ValueError):
    pass


@transaction.atomic
def store_asset(
    *, template_id: int, uploaded: UploadedFile, actor: User, correlation_id: str
) -> DocumentAsset:
    template = DocumentTemplate.objects.get(pk=template_id)
    content_type = uploaded.content_type or ""
    signature = ASSET_SIGNATURES.get(content_type)
    if (
        signature is None
        or uploaded.size is None
        or uploaded.size > MAX_ASSET_BYTES
        or uploaded.size == 0
    ):
        raise ValidationError({"file": "Only PNG or JPEG images up to 2 MiB are allowed."})
    start = uploaded.read(len(signature))
    uploaded.seek(0)
    if start != signature:
        raise ValidationError({"file": "Image content does not match its type."})
    extension = "png" if content_type == "image/png" else "jpg"
    key = f"document-assets/{template.pk}/{uuid4().hex}.{extension}"
    key = default_storage.save(key, uploaded)
    asset = DocumentAsset.objects.create(
        template=template,
        key=key,
        content_type=content_type,
        size=uploaded.size,
        uploaded_by=actor,
    )
    record_event(
        actor=actor,
        action_code="documents.asset_uploaded",
        target_type="documents.asset",
        target_identifier=str(asset.pk),
        correlation_id=correlation_id,
        metadata={"template_id": template.pk, "content_type": content_type, "size": asset.size},
    )
    return asset


def get_published_version(*, template_id: int, language: str) -> DocumentTemplateVersion | None:
    """Return a published language version only when the template has both languages."""
    if language not in ("en", "de"):
        return None
    published = DocumentTemplateVersion.objects.filter(
        template_id=template_id, status=VersionStatus.PUBLISHED
    )
    if not all(published.filter(language=required).exists() for required in ("en", "de")):
        return None
    return published.filter(language=language).order_by("-version").first()
