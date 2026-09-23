from collections.abc import Generator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.billing.models import Invoice
from pinaks.apps.configuration.models import CompanyProfile
from pinaks.apps.customers.models import Customer
from pinaks.apps.documents.models import DocumentTemplate, DocumentTemplateVersion, PreviewArtifact
from pinaks.apps.documents.preview_services import cleanup_expired_previews
from pinaks.apps.documents.renderer import PreviewRenderError, render_preview_html

pytestmark = pytest.mark.django_db


@pytest.fixture
def preview_setup(tmp_path: Path) -> Generator[tuple[APIClient, DocumentTemplate, Invoice]]:
    with override_settings(MEDIA_ROOT=tmp_path):
        actor = User.objects.create_user(
            username="preview-admin", password="test", role=UserRole.ADMIN
        )
        CompanyProfile.objects.create(legal_name="Seller GmbH")
        customer = Customer.objects.create(
            customer_number="P1", party_type="person", given_name="Ada", family_name="Lovelace"
        )
        invoice = Invoice.objects.create(
            customer=customer,
            document_language="en",
            issue_date=timezone.localdate(),
            subtotal=Decimal("10.00"),
            tax_total=Decimal("1.90"),
            grand_total=Decimal("11.90"),
        )
        template = DocumentTemplate.objects.create(code="invoice", name="Invoice")
        for language in ("en", "de"):
            DocumentTemplateVersion.objects.create(
                template=template,
                language=language,
                version=1,
                created_by=actor,
                html="<h1>{{ labels.invoice }}</h1><p>{{ invoice.grand_total | money }}</p>",
                page_settings={"size": "A4"},
            )
        client = APIClient()
        client.force_authenticate(user=actor)
        yield client, template, invoice


def test_bilingual_preview_uses_canonical_totals(
    preview_setup: tuple[APIClient, DocumentTemplate, Invoice],
) -> None:
    client, template, invoice = preview_setup
    for language, heading, total in (("en", "Invoice", "11.90"), ("de", "Rechnung", "11,90")):
        invoice.document_language = language
        invoice.save(update_fields=("document_language",))
        response = client.post(
            f"/api/v1/document-templates/{template.pk}/preview/",
            {"language": language, "invoice_id": invoice.pk, "format": "html"},
            format="json",
        )
        assert response.status_code == 201, response.content
        artifact = PreviewArtifact.objects.get(pk=response.json()["id"])
        downloaded = client.get(response.json()["url"])
        assert downloaded.status_code == 200
        assert heading in downloaded.content.decode()
        assert total in downloaded.content.decode()
        assert ("PREVIEW" if language == "en" else "VORSCHAU") in downloaded.content.decode()
        assert artifact.expires_at > timezone.now()
    invoice.refresh_from_db()
    assert invoice.grand_total == Decimal("11.90")


@pytest.mark.parametrize(
    "source",
    [
        "{{ invoice.__class__ }}",
        "{{ cycler.__init__ }}",
        "{{ invoice.grand_total.__class__ }}",
        "{% include '/etc/passwd' %}",
        "{% for x in range(1000000) %}x{% endfor %}",
        '<img src="https://example.test/a.png">',
        '<img src="file:///etc/passwd">',
        "<style>@import url(https://example.test/a.css)</style>",
        "<script>alert(1)</script>",
    ],
)
def test_unsafe_template_is_rejected(source: str) -> None:
    with pytest.raises(PreviewRenderError):
        render_preview_html(
            source, "", language="en", context={"invoice": {"grand_total": Decimal("1.00")}}
        )


def test_missing_variable_and_output_limit_are_rejected() -> None:
    with pytest.raises(PreviewRenderError):
        render_preview_html("{{ invoice.missing }}", "", language="en", context={"invoice": {}})
    with pytest.raises(PreviewRenderError):
        render_preview_html("x" * 300_000, "", language="en", context={})


def test_preview_requires_admin_and_expires(
    preview_setup: tuple[APIClient, DocumentTemplate, Invoice],
) -> None:
    client, template, _ = preview_setup
    response = client.post(
        f"/api/v1/document-templates/{template.pk}/preview/",
        {"language": "en", "format": "html"},
        format="json",
    )
    assert response.status_code == 201, response.content
    url = response.json()["url"]
    member = User.objects.create_user(
        username="preview-member", password="test", role=UserRole.COMPANY_MEMBER
    )
    member_client = APIClient()
    member_client.force_authenticate(user=member)
    assert member_client.get(url).status_code == 403
    assert (
        member_client.post(
            f"/api/v1/document-templates/{template.pk}/preview/", {"language": "en"}
        ).status_code
        == 403
    )
    artifact = PreviewArtifact.objects.get(pk=response.json()["id"])
    artifact.expires_at = timezone.now() - timedelta(seconds=1)
    artifact.save(update_fields=("expires_at",))
    assert client.get(url).status_code == 404
    assert cleanup_expired_previews() == 1
    assert not PreviewArtifact.objects.filter(pk=artifact.pk).exists()


def test_pdf_preview_is_downloaded_as_pdf(
    preview_setup: tuple[APIClient, DocumentTemplate, Invoice],
) -> None:
    client, template, _ = preview_setup
    response = client.post(
        f"/api/v1/document-templates/{template.pk}/preview/",
        {"language": "en", "format": "pdf"},
        format="json",
    )
    assert response.status_code == 201, response.content
    downloaded = client.get(response.json()["url"])
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"%PDF-")
    assert downloaded["Cache-Control"] == "no-store"


def test_missing_asset_is_rejected(
    preview_setup: tuple[APIClient, DocumentTemplate, Invoice],
) -> None:
    client, template, _ = preview_setup
    version = DocumentTemplateVersion.objects.get(template=template, language="en")
    version.html = '<img src="asset:missing.png">'
    version.save(update_fields=("html",))
    response = client.post(
        f"/api/v1/document-templates/{template.pk}/preview/",
        {"language": "en", "format": "html"},
        format="json",
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "preview_render_failed"


def test_declared_stored_image_is_embedded_without_file_access(
    preview_setup: tuple[APIClient, DocumentTemplate, Invoice],
) -> None:
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    from pinaks.apps.documents.models import DocumentAsset

    client, template, _ = preview_setup
    version = DocumentTemplateVersion.objects.get(template=template, language="en")
    image = b"\x89PNG\r\n\x1a\n" + b"x" * 200_000
    key = default_storage.save("document-assets/test.png", ContentFile(image))
    DocumentAsset.objects.create(
        template=template,
        key=key,
        content_type="image/png",
        size=len(image),
        uploaded_by=version.created_by,
    )
    version.html = f'<img src="asset:{key}">'
    version.asset_keys = [key]
    version.save(update_fields=("html", "asset_keys"))
    response = client.post(
        f"/api/v1/document-templates/{template.pk}/preview/",
        {"language": "en", "format": "html"},
        format="json",
    )
    assert response.status_code == 201, response.content
    downloaded = client.get(response.json()["url"])
    assert "data:image/png;base64," in downloaded.content.decode()
    assert "img-src data:" in downloaded["Content-Security-Policy"]
    assert key not in downloaded.content.decode()


def test_declared_asset_missing_from_storage_is_reported(
    preview_setup: tuple[APIClient, DocumentTemplate, Invoice],
) -> None:
    from pinaks.apps.documents.models import DocumentAsset

    client, template, _ = preview_setup
    version = DocumentTemplateVersion.objects.get(template=template, language="en")
    key = "document-assets/missing.png"
    DocumentAsset.objects.create(
        template=template,
        key=key,
        content_type="image/png",
        size=8,
        uploaded_by=version.created_by,
    )
    version.html = f'<img src="asset:{key}">'
    version.asset_keys = [key]
    version.save(update_fields=("html", "asset_keys"))
    response = client.post(
        f"/api/v1/document-templates/{template.pk}/preview/",
        {"language": "en", "format": "html"},
        format="json",
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "preview_render_failed"


def test_cleanup_command_removes_expired_previews(
    preview_setup: tuple[APIClient, DocumentTemplate, Invoice],
) -> None:
    from django.core.management import call_command

    client, template, _ = preview_setup
    response = client.post(
        f"/api/v1/document-templates/{template.pk}/preview/",
        {"language": "en", "format": "html"},
        format="json",
    )
    artifact = PreviewArtifact.objects.get(pk=response.json()["id"])
    artifact.expires_at = timezone.now() - timedelta(seconds=1)
    artifact.save(update_fields=("expires_at",))
    call_command("cleanup_document_previews")
    assert not PreviewArtifact.objects.filter(pk=artifact.pk).exists()


def test_nested_line_loops_are_rejected_before_rendering() -> None:
    source = (
        "{% for line in invoice.lines %}{% for line in invoice.lines %}x{% endfor %}{% endfor %}"
    )
    with pytest.raises(PreviewRenderError):
        render_preview_html(source, "", language="en", context={"invoice": {"lines": [1] * 200}})
