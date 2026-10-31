"""Final rendering consumes frozen data, never current business records."""

from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader

from pinaks.apps.documents.snapshot_renderer import SnapshotRenderError, WeasyPrintRenderer
from test_snapshot_xml import snapshot


def visual_snapshot(language: str = "en", exempt: bool = False) -> dict[str, object]:
    frozen = snapshot(language=language, exempt=exempt)
    frozen["template"] = {
        "language": language,
        "version_id": 42,
        "version": 1,
        "html": (
            "<h1>{{ labels.invoice }} {{ invoice.number }}</h1>"
            "<p>{{ seller.legal_name }} {{ customer.organization_name }} "
            "{{ recipient.organization_name }}</p>"
            "<p>{{ invoice.issue_date | date }} {{ invoice.grand_total | money }} EUR</p>"
            "<p>{{ seller.payment_instructions }} {{ seller.iban }}</p>"
            "<p>{{ invoice.exemption_wording }}</p>"
            '{% for line in invoice.lines %}<p class="line">{{ line.description }} '
            "{{ line.net_total | money }}</p>{% endfor %}"
        ),
        "css": ".line { break-before: page; }",
        "page_settings": {"size": "A4"},
        "asset_keys": [],
    }
    profile = frozen["tax_profile"]
    assert isinstance(profile, dict)
    profile["tax_column_policy"] = "hide" if exempt else "show"
    return frozen


@pytest.mark.parametrize("language", ["en", "de"])
@pytest.mark.parametrize("exempt", [False, True])
def test_final_pdf_uses_frozen_bilingual_values(language: str, exempt: bool) -> None:
    frozen = visual_snapshot(language, exempt)
    before = deepcopy(frozen)
    result = WeasyPrintRenderer().render(frozen)
    reader = PdfReader(BytesIO(result.pdf))
    text = " ".join(" ".join(page.extract_text() for page in reader.pages).split())
    for expected in (
        "INV-2026-0001",
        "Beispiel Dienstleistungen GmbH",
        "Other Company GmbH",
        "Beispiel Kunde GmbH",
        "DE89370400440532013000",
        "Rechnung" if language == "de" else "Invoice",
        "Beratung" if language == "de" else "Consulting",
        "15.09.2026" if language == "de" else "2026-09-15",
        ("200,00" if exempt else "238,00")
        if language == "de"
        else ("200.00" if exempt else "238.00"),
    ):
        assert expected in text
    if exempt:
        assert ("Steuerbefreit" if language == "de" else "Exempt from VAT") in text
    assert "PREVIEW" not in text and "VORSCHAU" not in text
    assert ("Invoice" if language == "de" else "Rechnung") not in text
    assert len(reader.pages) == 2
    assert float(reader.pages[0].mediabox.width) == pytest.approx(595.28, abs=0.1)
    assert result.renderer == "WeasyPrint"
    assert result.renderer_version
    assert result.template_version_id == 42
    assert frozen == before


@pytest.mark.parametrize("change", ["language", "schema", "page", "unsafe", "variable", "asset"])
def test_invalid_final_input_fails_closed(change: str) -> None:
    frozen = visual_snapshot()
    template = frozen["template"]
    assert isinstance(template, dict)
    if change == "language":
        template["language"] = "de"
    elif change == "schema":
        frozen["schema_version"] = 2
    elif change == "page":
        template["page_settings"] = {"size": "A3"}
    elif change == "unsafe":
        template["html"] = '<img src="file:///etc/passwd">'
    elif change == "variable":
        template["html"] = "{{ invoice.missing }}"
    else:
        template["html"] = '<img src="asset:missing.png">'
    with pytest.raises(SnapshotRenderError) as error:
        WeasyPrintRenderer().render(frozen)
    assert error.value.code == "visual_render_failed"


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["missing", "corrupt", "changed", "valid"])
def test_controlled_final_assets(tmp_path: object, state: str) -> None:
    import base64

    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    from django.test import override_settings

    from pinaks.apps.accounts.models import User
    from pinaks.apps.documents.models import DocumentAsset, DocumentTemplate

    actor = User.objects.create_user(username="asset-renderer")
    template_record = DocumentTemplate.objects.create(code="final", name="Final")
    payload = (
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII="
        )
        if state == "valid"
        else b"corrupt-image"
    )
    with override_settings(MEDIA_ROOT=tmp_path):
        key = "document-assets/final.png"
        if state != "missing":
            default_storage.save(key, ContentFile(payload))
        DocumentAsset.objects.create(
            template=template_record,
            key=key,
            content_type="image/png",
            size=len(payload) + (1 if state == "changed" else 0),
            uploaded_by=actor,
        )
        frozen = visual_snapshot()
        template = frozen["template"]
        assert isinstance(template, dict)
        template.update(id=template_record.pk, asset_keys=[key], html=f'<img src="asset:{key}">')
        if state == "valid":
            assert WeasyPrintRenderer().render(frozen).pdf.startswith(b"%PDF-")
        else:
            with pytest.raises(SnapshotRenderError):
                WeasyPrintRenderer().render(frozen)


@pytest.mark.parametrize(
    "source",
    [
        "{{ invoice.__class__ }}",
        "{% include '/etc/passwd' %}",
        '<img src="https://example.test/a.png">',
        "<style>@import url(https://example.test/a.css)</style>",
        "<script>alert(1)</script>",
    ],
)
def test_final_renderer_reuses_template_sandbox(source: str) -> None:
    frozen = visual_snapshot()
    template = frozen["template"]
    assert isinstance(template, dict)
    template["html"] = source
    with pytest.raises(SnapshotRenderError):
        WeasyPrintRenderer().render(frozen)


@pytest.mark.parametrize("policy", ["show", "hide"])
def test_frozen_tax_column_policy_controls_presentation(policy: str) -> None:
    frozen = visual_snapshot()
    profile = frozen["tax_profile"]
    template = frozen["template"]
    assert isinstance(profile, dict) and isinstance(template, dict)
    profile["tax_column_policy"] = policy
    template["html"] = (
        "<p>{{ invoice.grand_total | money }}</p>"
        "<p data-tax-column>Tax column {{ invoice.tax_total | money }}</p>"
    )
    pdf = WeasyPrintRenderer().render(frozen).pdf
    text = PdfReader(BytesIO(pdf)).pages[0].extract_text()
    assert ("Tax column" in text) == (policy == "show")
    assert "238.00" in text
