from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from uuid import uuid4

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from pinaks.apps.workers.models import WorkItem, WorkState

Handler = Callable[[WorkItem], None]
DEFAULT_LEASE = timedelta(minutes=5)
MAX_BACKOFF = timedelta(hours=1)


def enqueue_work(
    *, job_type: str, identity: str, scheduled_at: datetime | None = None, max_attempts: int = 5
) -> WorkItem:
    """Create one durable work item per logical operation."""
    item, _ = WorkItem.objects.get_or_create(
        job_type=job_type,
        identity=identity,
        defaults={"scheduled_at": scheduled_at or timezone.now(), "max_attempts": max_attempts},
    )
    return item


def claim_work(
    *, now: datetime | None = None, lease_duration: timedelta = DEFAULT_LEASE
) -> WorkItem | None:
    current = now or timezone.now()
    with transaction.atomic():
        WorkItem.objects.filter(
            state=WorkState.RUNNING,
            lease_until__lte=current,
            attempt_count__gte=F("max_attempts"),
        ).update(
            state=WorkState.FAILED,
            lease_until=None,
            lease_token=None,
            failure_code="lease_expired",
        )
        item = (
            WorkItem.objects.select_for_update(skip_locked=True)
            .filter(attempt_count__lt=F("max_attempts"))
            .filter(
                Q(state=WorkState.QUEUED, scheduled_at__lte=current)
                | Q(state=WorkState.RUNNING, lease_until__lte=current)
            )
            .order_by("scheduled_at", "pk")
            .first()
        )
        if item is None:
            return None
        item.state = WorkState.RUNNING
        item.attempt_count += 1
        item.lease_token = uuid4()
        item.lease_until = current + lease_duration
        item.failure_code = ""
        item.save(
            update_fields=[
                "state",
                "attempt_count",
                "lease_token",
                "lease_until",
                "failure_code",
                "updated_at",
            ]
        )
        return item


def finish_work(item: WorkItem, *, now: datetime | None = None) -> bool:
    current = now or timezone.now()
    return bool(
        WorkItem.objects.filter(
            pk=item.pk,
            state=WorkState.RUNNING,
            lease_token=item.lease_token,
            lease_until__gt=current,
        ).update(state=WorkState.SUCCEEDED, lease_until=None, lease_token=None, failure_code="")
    )


def fail_work(item: WorkItem, *, now: datetime, code: str = "handler_error") -> bool:
    if item.attempt_count >= item.max_attempts:
        state, schedule = WorkState.FAILED, item.scheduled_at
    else:
        state = WorkState.QUEUED
        delay = min(10 * 2 ** (item.attempt_count - 1), int(MAX_BACKOFF.total_seconds()))
        schedule = now + timedelta(seconds=delay)
    return bool(
        WorkItem.objects.filter(
            pk=item.pk,
            state=WorkState.RUNNING,
            lease_token=item.lease_token,
            lease_until__gt=now,
        ).update(
            state=state,
            scheduled_at=schedule,
            lease_until=None,
            lease_token=None,
            failure_code=code,
        )
    )


def run_one(*, handlers: Mapping[str, Handler], now: datetime | None = None) -> bool:
    current = now or timezone.now()
    item = claim_work(now=current)
    if item is None:
        return False
    handler = handlers.get(item.job_type)
    if handler is None:
        fail_work(item, now=now or timezone.now(), code="unknown_job_type")
        return False
    try:
        handler(item)
    except Exception:
        # Exception text can contain customer or provider data. Persist only this stable code.
        fail_work(item, now=now or timezone.now())
        return False
    return finish_work(item)
