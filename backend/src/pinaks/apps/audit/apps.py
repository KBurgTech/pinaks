from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pinaks.apps.audit"
    label = "audit"

    def ready(self) -> None:
        from pinaks.apps.audit import receivers  # noqa: F401
