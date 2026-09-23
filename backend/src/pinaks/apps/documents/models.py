from typing import Any, ClassVar
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class DocumentTemplate(models.Model):
    code: models.SlugField[str, str] = models.SlugField(max_length=80, unique=True)
    name: models.CharField[str, str] = models.CharField(max_length=120)
    created_at: models.DateTimeField[Any, Any] = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("code",)

    def __str__(self) -> str:
        return self.name


class VersionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"


class DocumentTemplateVersionQuerySet(models.QuerySet["DocumentTemplateVersion"]):
    def update(self, **kwargs: object) -> int:
        if self.filter(status=VersionStatus.PUBLISHED).exists():
            raise ValueError("Published template versions are immutable.")
        return super().update(**kwargs)

    def delete(self) -> tuple[int, dict[str, int]]:
        if self.filter(status=VersionStatus.PUBLISHED).exists():
            raise ValueError("Published template versions are immutable.")
        return super().delete()


class DocumentTemplateVersion(models.Model):
    template: models.ForeignKey[DocumentTemplate, DocumentTemplate] = models.ForeignKey(
        DocumentTemplate, on_delete=models.PROTECT, related_name="versions"
    )
    language: models.CharField[str, str] = models.CharField(
        max_length=2, choices=(("en", "English"), ("de", "German"))
    )
    version: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    status: models.CharField[str, str] = models.CharField(
        max_length=10, choices=VersionStatus, default=VersionStatus.DRAFT
    )
    html: models.TextField[str, str] = models.TextField(blank=True)
    css: models.TextField[str, str] = models.TextField(blank=True)
    page_settings: models.JSONField[dict[str, object], dict[str, object]] = models.JSONField(
        default=dict, blank=True
    )
    asset_keys: models.JSONField[list[str], list[str]] = models.JSONField(default=list, blank=True)
    created_by: models.ForeignKey[Any, Any] = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_template_versions"
    )
    published_by: models.ForeignKey[Any | None, Any | None] = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="published_template_versions",
    )
    created_at: models.DateTimeField[Any, Any] = models.DateTimeField(auto_now_add=True)
    published_at: models.DateTimeField[Any | None, Any | None] = models.DateTimeField(
        null=True, blank=True
    )

    objects = DocumentTemplateVersionQuerySet.as_manager()

    class Meta:
        ordering = ("language", "-version")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("template", "language", "version"), name="unique_template_language_version"
            ),
            models.UniqueConstraint(
                fields=("template", "language"),
                condition=Q(status=VersionStatus.DRAFT),
                name="one_draft_per_template_language",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.template.code} {self.language} v{self.version}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding and self.pk is not None:
            stored = DocumentTemplateVersion.objects.get(pk=self.pk)
            if stored.status == VersionStatus.PUBLISHED:
                raise ValidationError("Published template versions are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if self.status == VersionStatus.PUBLISHED:
            raise ValidationError("Published template versions are immutable.")
        return super().delete(*args, **kwargs)


class DocumentAsset(models.Model):
    template: models.ForeignKey[DocumentTemplate, DocumentTemplate] = models.ForeignKey(
        DocumentTemplate, on_delete=models.PROTECT, related_name="assets"
    )
    key: models.CharField[str, str] = models.CharField(max_length=255, unique=True)
    content_type: models.CharField[str, str] = models.CharField(max_length=30)
    size: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    uploaded_by: models.ForeignKey[Any, Any] = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    created_at: models.DateTimeField[Any, Any] = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.key


class PreviewArtifact(models.Model):
    """Short-lived, isolated output of a non-authoritative preview."""

    id: models.UUIDField[Any, Any] = models.UUIDField(
        primary_key=True, default=uuid4, editable=False
    )
    created_by: models.ForeignKey[Any, Any] = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="document_previews"
    )
    storage_key: models.CharField[str, str] = models.CharField(max_length=255, unique=True)
    content_type: models.CharField[str, str] = models.CharField(max_length=40)
    expires_at: models.DateTimeField[Any, Any] = models.DateTimeField()
    created_at: models.DateTimeField[Any, Any] = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return str(self.pk)
