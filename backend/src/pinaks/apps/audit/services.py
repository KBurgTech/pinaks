from collections.abc import Mapping
from uuid import uuid4

from django.http import HttpRequest

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.models import AuditEvent


def request_correlation_id(request: HttpRequest | None) -> str:
    if request is not None:
        supplied_id = request.headers.get("X-Request-ID", "").strip()
        if supplied_id:
            return supplied_id[:255]
    return str(uuid4())


def record_event(
    *,
    action_code: str,
    target_type: str,
    target_identifier: str = "",
    actor: User | None = None,
    correlation_id: str | None = None,
    request: HttpRequest | None = None,
    metadata: Mapping[str, object] | None = None,
) -> AuditEvent:
    """Record safe audit evidence on behalf of another application module."""
    event = AuditEvent(
        actor=actor,
        action_code=action_code,
        target_type=target_type,
        target_identifier=target_identifier,
        correlation_id=correlation_id or request_correlation_id(request),
        metadata=dict(metadata or {}),
    )
    event.full_clean()
    event._allow_service_insert = True
    event.save(force_insert=True)
    event._allow_service_insert = False
    return event
