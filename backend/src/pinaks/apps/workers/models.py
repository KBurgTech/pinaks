from datetime import datetime
from typing import ClassVar
from uuid import UUID

from django.db import models
from django.db.models import Q
from django.utils import timezone


class WorkState(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class WorkItem(models.Model):
    job_type: models.CharField[str, str] = models.CharField(max_length=100)
    identity: models.CharField[str, str] = models.CharField(max_length=255)
    state: models.CharField[str, str] = models.CharField(
        max_length=16, choices=WorkState, default=WorkState.QUEUED
    )
    scheduled_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        default=timezone.now
    )
    attempt_count: models.PositiveSmallIntegerField[int, int] = models.PositiveSmallIntegerField(
        default=0
    )
    max_attempts: models.PositiveSmallIntegerField[int, int] = models.PositiveSmallIntegerField(
        default=5
    )
    lease_until: models.DateTimeField[datetime | None, datetime | None] = models.DateTimeField(
        null=True, blank=True
    )
    lease_token: models.UUIDField[UUID | None, UUID | None] = models.UUIDField(
        null=True, blank=True, editable=False
    )
    failure_code: models.CharField[str, str] = models.CharField(max_length=32, blank=True)
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["job_type", "identity"], name="work_unique_identity"),
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1), name="work_positive_max_attempts"
            ),
            models.CheckConstraint(
                condition=Q(attempt_count__lte=models.F("max_attempts")),
                name="work_attempts_bounded",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state=WorkState.RUNNING, lease_until__isnull=False, lease_token__isnull=False)
                    | Q(
                        state__in=[WorkState.QUEUED, WorkState.SUCCEEDED, WorkState.FAILED],
                        lease_until__isnull=True,
                        lease_token__isnull=True,
                    )
                ),
                name="work_running_has_lease",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["state", "scheduled_at"], name="work_ready_idx")
        ]

    def __str__(self) -> str:
        return f"{self.job_type}: {self.pk} ({self.state})"
