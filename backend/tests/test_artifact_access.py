from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User
from pinaks.apps.billing.issuance import issue_invoice
from pinaks.apps.billing.models import Invoice
from pinaks.apps.documents.models import DocumentTemplate, DocumentTemplateVersion, IssuedArtifact
from test_issuance import ready_invoice as issuance_ready  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def stored_invoice(
    issuance_ready: tuple[Invoice, User, DocumentTemplate],  # noqa: F811
    tmp_path: Path,
) -> Iterator[tuple[Invoice, User]]:
    invoice, actor, template = issuance_ready
    invoice = issue_invoice(
        invoice_id=invoice.pk,
        expected_version=invoice.version,
        template_id=template.pk,
        idempotency_key="download",
        actor=actor,
        correlation_id="test",
    )
    version = DocumentTemplateVersion.objects.filter(template=template, language="en").first()
    assert version is not None
    for kind in ("pdf", "xml", "report"):
        data = f"original {kind}".encode()
        key = f"{'a' * 64}/{kind}"
        path = tmp_path / key
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        IssuedArtifact.objects.create(
            invoice=invoice,
            kind=kind,
            storage_key=key,
            sha256=sha256(data).hexdigest(),
            size=len(data),
            standard="Factur-X",
            profile="EN 16931",
            specification_version="1.09",
            template_version=version,
            generated_at=invoice.modified_at,
        )
    from pinaks.apps.billing.issuance import finalize_issuance

    finalize_issuance(invoice_id=invoice.pk)
    invoice.refresh_from_db()
    with override_settings(ISSUED_DOCUMENT_ROOT=tmp_path):
        yield invoice, actor


@pytest.mark.parametrize("role", ["admin", "company_member", "read_only"])
def test_authorized_original_downloads(stored_invoice: tuple[Invoice, User], role: str) -> None:
    invoice, _ = stored_invoice
    actor = User.objects.create_user(username=role, role=role)
    client = APIClient()
    client.force_authenticate(actor)
    metadata = client.get(f"/api/v1/invoices/{invoice.pk}/documents/")
    assert metadata.status_code == 200
    assert metadata.data["healthy"] is True
    assert "storage_key" not in str(metadata.data)
    for kind, mime in (
        ("pdf", "application/pdf"),
        ("xml", "application/xml"),
        ("report", "application/json"),
    ):
        response = client.get(f"/api/v1/invoices/{invoice.pk}/documents/{kind}/")
        assert response.status_code == 200
        assert response.content == f"original {kind}".encode()
        assert response["Content-Type"] == mime
        assert response["Content-Disposition"].startswith("attachment;")
        assert response["Cache-Control"] == "no-store"
        assert response["X-Content-Type-Options"] == "nosniff"


def test_anonymous_inactive_and_unknown_downloads_are_denied(
    stored_invoice: tuple[Invoice, User],
) -> None:
    invoice, actor = stored_invoice
    client = APIClient()
    url = f"/api/v1/invoices/{invoice.pk}/documents/pdf/"
    assert client.get(url).status_code == 403
    actor.is_active = False
    actor.save()
    client.force_authenticate(actor)
    assert client.get(url).status_code == 403
    actor.is_active = True
    actor.save()
    assert client.get(f"/api/v1/invoices/{invoice.pk}/documents/unknown/").status_code == 404
    assert client.get(f"/api/v1/invoices/{invoice.pk}/documents/../../secret/").status_code == 404


@pytest.mark.parametrize("damage", ["missing", "changed", "symlink"])
def test_unhealthy_evidence_is_never_returned_or_recreated(
    stored_invoice: tuple[Invoice, User], tmp_path: Path, damage: str
) -> None:
    invoice, actor = stored_invoice
    path = tmp_path / ("a" * 64) / "pdf"
    if damage == "changed":
        path.write_bytes(b"tampered")
    else:
        path.unlink()
        if damage == "symlink":
            outside = tmp_path / "outside"
            outside.write_bytes(b"original pdf")
            path.symlink_to(outside)
    client = APIClient()
    client.force_authenticate(actor)
    metadata = client.get(f"/api/v1/invoices/{invoice.pk}/documents/")
    assert metadata.status_code == 200
    assert metadata.data["healthy"] is False
    response = client.get(f"/api/v1/invoices/{invoice.pk}/documents/pdf/")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "artifact_integrity_failed"
    invoice.refresh_from_db()
    assert invoice.lifecycle_status == "ISSUED"
    from pinaks.apps.documents.access import verify_issued_documents

    assert verify_issued_documents() == [invoice.pk]


@pytest.mark.parametrize(
    "key", ["../../secret", "/etc/passwd", "a" * 64 + "/../pdf", "a" * 64 + "/xml"]
)
def test_storage_keys_cannot_escape_or_select_another_kind(
    stored_invoice: tuple[Invoice, User], key: str
) -> None:
    from pinaks.apps.documents.access import read_artifact
    from pinaks.apps.documents.issuance import ArtifactIntegrityError

    invoice, _ = stored_invoice
    artifact = IssuedArtifact.objects.get(invoice=invoice, kind="pdf")
    artifact.storage_key = key
    with pytest.raises(ArtifactIntegrityError):
        read_artifact(artifact)


def test_integrity_command_reports_unhealthy_evidence(
    stored_invoice: tuple[Invoice, User], tmp_path: Path
) -> None:
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError

    output = StringIO()
    call_command("verify_issued_documents", stdout=output)
    assert "healthy" in output.getvalue()
    (tmp_path / ("a" * 64) / "xml").unlink()
    with pytest.raises(CommandError, match="integrity"):
        call_command("verify_issued_documents", stdout=output)
