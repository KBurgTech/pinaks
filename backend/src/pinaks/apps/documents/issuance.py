"""Recoverable filesystem publication followed by transactional issuance finalization."""

import json
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import mkdtemp

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from pinaks.apps.billing.issuance import finalize_issuance
from pinaks.apps.billing.models import Invoice, LifecycleStatus
from pinaks.apps.documents.models import IssuedArtifact
from pinaks.apps.e_invoicing.generation import HybridInvoiceGenerator
from pinaks.apps.e_invoicing.snapshot import obj, string
from pinaks.apps.workers.models import WorkItem


class ArtifactIntegrityError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("artifact_integrity_failed")


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _publish(root: Path, key: str, snapshot: dict[str, object]) -> None:
    """Publish a complete bundle atomically. Never modify a published directory."""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = Path(mkdtemp(prefix=".issuance-", dir=root))
    try:
        generated = HybridInvoiceGenerator().generate(snapshot)
        report = json.dumps(
            {
                "xml": {
                    **asdict(generated.xml_report),
                    "raw_report": generated.xml_report.raw_report.decode("utf-8"),
                },
                "pdf": {
                    **asdict(generated.pdf_report),
                    "raw_report": generated.pdf_report.raw_report.decode("utf-8"),
                },
                "renderer": generated.visual.renderer,
                "renderer_version": generated.visual.renderer_version,
            },
            sort_keys=True,
        ).encode()
        payloads = {"pdf": generated.pdf, "xml": generated.xml, "report": report}
        manifest = {
            "snapshot_hash": key,
            "standard": generated.standard,
            "profile": generated.profile,
            "specification_version": generated.specification_version,
            "template_version_id": generated.visual.template_version_id,
            "generated_at": timezone.now().isoformat(),
            "artifacts": {
                kind: {"sha256": _digest(data), "size": len(data)}
                for kind, data in payloads.items()
            },
        }
        for kind, data in {
            **payloads,
            "manifest": json.dumps(manifest, sort_keys=True).encode(),
        }.items():
            path = temporary / kind
            with path.open("xb") as handle:
                os.chmod(path, 0o600)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        with _directory(temporary) as descriptor:
            os.fsync(descriptor)
        os.rename(temporary, root / key)
        with _directory(root) as descriptor:
            os.fsync(descriptor)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


@contextmanager
def _directory(path: Path) -> Iterator[int]:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@transaction.atomic
def generate_invoice(*, invoice_id: int) -> None:
    # Serializes handlers even after a worker lease expires. The filesystem commit
    # deliberately survives database rollback and is reused on the next attempt.
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    if invoice.lifecycle_status == LifecycleStatus.ISSUED:
        return
    if invoice.lifecycle_status != LifecycleStatus.ISSUING or invoice.snapshot is None:
        raise ValueError("invoice_not_issuing")
    snapshot = invoice.snapshot
    key = _digest(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode())
    root = Path(settings.ISSUED_DOCUMENT_ROOT)
    bundle = root / key
    if not bundle.exists():
        _publish(root, key, snapshot)
    try:
        manifest = obj(json.loads((bundle / "manifest").read_bytes()))
        if manifest["snapshot_hash"] != key:
            raise ArtifactIntegrityError()
        generated_at = parse_datetime(string(manifest["generated_at"]))
        if generated_at is None:
            raise ArtifactIntegrityError()
        artifacts = obj(manifest["artifacts"])
        for kind in ("pdf", "xml", "report"):
            metadata = obj(artifacts[kind])
            data = (bundle / kind).read_bytes()
            if metadata["sha256"] != _digest(data) or metadata["size"] != len(data):
                raise ArtifactIntegrityError()
            template = obj(snapshot["template"])
            IssuedArtifact.objects.create(
                invoice_id=invoice_id,
                kind=kind,
                storage_key=f"{key}/{kind}",
                sha256=_digest(data),
                size=len(data),
                standard=string(manifest["standard"]),
                profile=string(manifest["profile"]),
                specification_version=string(manifest["specification_version"]),
                template_version_id=template["version_id"],
                generated_at=generated_at,
            )
    except (KeyError, ValueError, TypeError) as error:
        raise ArtifactIntegrityError() from error
    finalize_issuance(invoice_id=invoice_id)


def handle_generation(item: WorkItem) -> None:
    generate_invoice(invoice_id=int(item.identity))
