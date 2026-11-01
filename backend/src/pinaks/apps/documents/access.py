"""Read original evidence through fixed kinds, with fail-closed integrity checks."""

import os
import re
import stat
from hashlib import sha256
from pathlib import Path

from django.conf import settings

from pinaks.apps.billing.models import Invoice, LifecycleStatus
from pinaks.apps.documents.issuance import ArtifactIntegrityError
from pinaks.apps.documents.models import IssuedArtifact


def read_artifact(artifact: IssuedArtifact) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}/(pdf|xml|report)", artifact.storage_key):
        raise ArtifactIntegrityError()
    bundle, kind = artifact.storage_key.split("/")
    if kind != artifact.kind:
        raise ArtifactIntegrityError()
    try:
        # Open relative to directory descriptors; reject links at both levels.
        root = os.open(Path(settings.ISSUED_DOCUMENT_ROOT), os.O_RDONLY | os.O_DIRECTORY)
        try:
            directory = os.open(bundle, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            try:
                descriptor = os.open(
                    kind, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
                )
                with os.fdopen(descriptor, "rb") as handle:
                    if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                        raise ArtifactIntegrityError()
                    data = handle.read()
            finally:
                os.close(directory)
        finally:
            os.close(root)
    except OSError as error:
        raise ArtifactIntegrityError() from error
    if len(data) != artifact.size or sha256(data).hexdigest() != artifact.sha256:
        raise ArtifactIntegrityError()
    return data


def artifacts_healthy(artifacts: list[IssuedArtifact]) -> bool:
    if {artifact.kind for artifact in artifacts} != {"pdf", "xml", "report"}:
        return False
    try:
        for artifact in artifacts:
            read_artifact(artifact)
    except ArtifactIntegrityError:
        return False
    return True


def verify_issued_documents() -> list[int]:
    """Return unhealthy issued invoice IDs for health and backup verification."""
    return [
        invoice.pk
        for invoice in Invoice.objects.filter(
            lifecycle_status__in=(LifecycleStatus.ISSUED, LifecycleStatus.CANCELLED)
        ).iterator(chunk_size=100)
        if not artifacts_healthy(list(IssuedArtifact.objects.filter(invoice=invoice)))
    ]
