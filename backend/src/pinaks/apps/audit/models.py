import re
from collections.abc import Mapping, Sequence
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from pinaks.apps.accounts.models import User

PROHIBITED_METADATA_KEYS = frozenset(
    {
        "address",
        "authorization",
        "contact_details",
        "cookie",
        "credential",
        "credentials",
        "custom_data",
        "custom_field",
        "custom_fields",
        "email",
        "invoice_content",
        "invoice_contents",
        "invoice_line",
        "invoice_lines",
        "password",
        "passphrase",
        "phone",
        "secret",
        "secrets",
        "token",
        "tokens",
    }
)


def _validate_safe_metadata(value: object) -> None:
    if isinstance(value, Mapping):
        for raw_key, nested_value in value.items():
            normalized_key = re.sub(r"[^a-z0-9]+", "_", str(raw_key).lower()).strip("_")
            if normalized_key in PROHIBITED_METADATA_KEYS:
                raise ValidationError(
                    {"metadata": f"Metadata contains prohibited sensitive key: {raw_key}."}
                )
            _validate_safe_metadata(nested_value)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested_value in value:
            _validate_safe_metadata(nested_value)


class AuditEventQuerySet(models.QuerySet["AuditEvent"]):
    def update(self, **kwargs: object) -> int:
        raise ValueError("Audit events are immutable.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValueError("Audit events are immutable.")


class AuditEventManager(models.Manager["AuditEvent"]):
    def get_queryset(self) -> AuditEventQuerySet:
        return AuditEventQuerySet(model=self.model, using=self._db)

    def create(self, **kwargs: object) -> AuditEvent:
        raise ValueError("Use the public record_event service to create audit events.")


class AuditEvent(models.Model):
    actor: models.ForeignKey[User | None, User | None] = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    action_code: models.CharField[str, str] = models.CharField(max_length=100)
    target_type: models.CharField[str, str] = models.CharField(max_length=100)
    target_identifier: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    timestamp: models.DateTimeField[Any, Any] = models.DateTimeField(auto_now_add=True)
    correlation_id: models.CharField[str, str] = models.CharField(max_length=255)
    metadata: models.JSONField[dict[str, object], dict[str, object]] = models.JSONField(
        default=dict, blank=True
    )

    objects = AuditEventManager()
    _allow_service_insert = False

    class Meta:
        ordering = ("timestamp", "pk")

    def __str__(self) -> str:
        return f"{self.timestamp}: {self.action_code}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding or not self._allow_service_insert:
            raise ValueError("Audit events are immutable and may only be recorded by the service.")
        super().save(*args, **kwargs)

    def delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        del using, keep_parents
        raise ValueError("Audit events are immutable.")

    def clean(self) -> None:
        super().clean()
        _validate_safe_metadata(self.metadata)
