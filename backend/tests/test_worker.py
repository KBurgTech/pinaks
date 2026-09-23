from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.core.management import call_command
from django.utils import timezone

from pinaks.apps.workers.models import WorkItem, WorkState
from pinaks.apps.workers.services import claim_work, enqueue_work, fail_work, finish_work, run_one

pytestmark = pytest.mark.django_db(transaction=True)


def test_enqueue_is_idempotent_and_scheduled_work_waits() -> None:
    now = timezone.now()
    first = enqueue_work(
        job_type="test.task", identity="one", scheduled_at=now + timedelta(minutes=5)
    )
    second = enqueue_work(job_type="test.task", identity="one")
    assert first.pk == second.pk
    assert claim_work(now=now) is None
    assert claim_work(now=now + timedelta(minutes=5)) is not None


def test_concurrent_workers_claim_distinct_records() -> None:
    enqueue_work(job_type="test.task", identity="one")
    enqueue_work(job_type="test.task", identity="two")
    barrier = Barrier(2)

    def claim() -> WorkItem | None:
        barrier.wait()
        return claim_work()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert all(item is not None for item in results)
    assert len({item.pk for item in results if item is not None}) == 2
    assert claim_work() is None


def test_expired_lease_recovers_and_stale_owner_cannot_finish() -> None:
    now = timezone.now()
    enqueue_work(job_type="test.task", identity="one", scheduled_at=now)
    original = claim_work(now=now, lease_duration=timedelta(seconds=30))
    assert original is not None
    assert not finish_work(original, now=now + timedelta(seconds=31))
    assert not fail_work(original, now=now + timedelta(seconds=31))
    recovered = claim_work(now=now + timedelta(seconds=31))
    assert recovered is not None
    assert recovered.pk == original.pk
    assert recovered.attempt_count == 2
    assert recovered.lease_token != original.lease_token
    assert not finish_work(original)
    assert finish_work(recovered)
    recovered.refresh_from_db()
    assert recovered.state == WorkState.SUCCEEDED


def test_failure_retries_with_bounded_backoff_then_stops() -> None:
    now = timezone.now()
    item = enqueue_work(job_type="test.task", identity="one", scheduled_at=now, max_attempts=3)
    for attempt, delay in [(1, 10), (2, 20), (3, None)]:
        assert not run_one(handlers={"test.task": lambda _: raise_error()}, now=now)
        item.refresh_from_db()
        assert item.attempt_count == attempt
        assert item.failure_code == "handler_error"
        if delay is None:
            assert item.state == WorkState.FAILED
        else:
            assert item.state == WorkState.QUEUED
            assert item.scheduled_at == now + timedelta(seconds=delay)
            assert claim_work(now=now + timedelta(seconds=delay - 1)) is None
            now += timedelta(seconds=delay)
    assert claim_work(now=now + timedelta(days=1)) is None


def raise_error() -> None:
    raise ValueError("secret customer details must not be saved")


def test_handler_crash_is_sanitized_and_interruption_preserves_lease() -> None:
    now = timezone.now()
    item = enqueue_work(job_type="test.task", identity="one", scheduled_at=now)
    assert not run_one(handlers={"test.task": lambda _: raise_error()}, now=now)
    item.refresh_from_db()
    assert "secret" not in str(item.__dict__)
    assert item.failure_code == "handler_error"
    item.scheduled_at = now
    item.save(update_fields=["scheduled_at"])

    def interrupt(_: WorkItem) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_one(handlers={"test.task": interrupt}, now=now)
    item.refresh_from_db()
    assert item.state == WorkState.RUNNING
    assert claim_work(now=now) is None
    assert claim_work(now=now + timedelta(minutes=6)) is not None


def test_worker_command_exits_cleanly_with_no_work() -> None:
    call_command("run_worker", "--once")


def test_database_rejects_invalid_state() -> None:
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        WorkItem.objects.create(job_type="test.task", identity="bad", state="invalid")


def test_expired_final_attempt_becomes_terminal() -> None:
    now = timezone.now()
    item = enqueue_work(job_type="test.task", identity="one", scheduled_at=now, max_attempts=1)
    assert claim_work(now=now, lease_duration=timedelta(seconds=1)) is not None
    assert claim_work(now=now + timedelta(seconds=2)) is None
    item.refresh_from_db()
    assert item.state == WorkState.FAILED
    assert item.failure_code == "lease_expired"


def test_worker_command_stops_on_sigterm(monkeypatch: pytest.MonkeyPatch) -> None:
    import signal

    from pinaks.apps.workers.management.commands import run_worker

    polls = 0

    def request_stop(_seconds: float) -> None:
        nonlocal polls
        polls += 1
        signal.raise_signal(signal.SIGTERM)

    monkeypatch.setattr(run_worker, "sleep", request_stop)
    call_command("run_worker", poll_seconds=0.01)
    assert polls == 1


def test_retry_delay_caps_at_one_hour() -> None:
    now = timezone.now()
    item = enqueue_work(job_type="test.task", identity="one", scheduled_at=now, max_attempts=12)
    for attempt in range(10):
        previous = now
        assert not run_one(handlers={"test.task": lambda _: raise_error()}, now=now)
        item.refresh_from_db()
        assert item.scheduled_at - previous == timedelta(seconds=min(10 * 2**attempt, 3600))
        now = item.scheduled_at
    assert item.state == WorkState.QUEUED
