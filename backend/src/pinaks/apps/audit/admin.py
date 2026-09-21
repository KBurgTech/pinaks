from django.contrib import admin
from django.http import HttpRequest

from pinaks.apps.audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("timestamp", "action_code", "target_type", "target_identifier", "actor")
    readonly_fields = (
        "actor",
        "action_code",
        "target_type",
        "target_identifier",
        "timestamp",
        "correlation_id",
        "metadata",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: AuditEvent | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: AuditEvent | None = None) -> bool:
        return False
