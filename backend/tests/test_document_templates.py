from io import BytesIO
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.models import AuditEvent
from pinaks.apps.documents.models import DocumentTemplateVersion

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client() -> APIClient:
    user = User.objects.create_user(username="template-admin", password="test", role=UserRole.ADMIN)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _create_pair(client: APIClient) -> tuple[int, dict[str, int]]:
    response = client.post(
        "/api/v1/document-templates/", {"code": "invoice", "name": "Invoice"}, format="json"
    )
    assert response.status_code == 201, response.json()
    template_id = response.json()["id"]
    versions = {}
    for language in ("en", "de"):
        response = client.post(
            f"/api/v1/document-templates/{template_id}/versions/",
            {
                "language": language,
                "html": f"<h1>{language} invoice</h1>",
                "css": "h1 { color: black; }",
                "page_settings": {"size": "A4"},
                "asset_keys": [],
            },
            format="json",
        )
        assert response.status_code == 201, response.json()
        versions[language] = response.json()["id"]
    return template_id, versions


def test_publish_requires_both_languages_and_preserves_published_history(
    admin_client: APIClient,
) -> None:
    response = admin_client.post(
        "/api/v1/document-templates/", {"code": "receipt", "name": "Receipt"}, format="json"
    )
    template_id = response.json()["id"]
    only_en = admin_client.post(
        f"/api/v1/document-templates/{template_id}/versions/",
        {
            "language": "en",
            "html": "<h1>Receipt</h1>",
            "css": "",
            "page_settings": {"size": "A4"},
            "asset_keys": [],
        },
        format="json",
    )
    assert only_en.status_code == 201, only_en.json()
    missing = admin_client.post(f"/api/v1/document-templates/{template_id}/publish/")
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "template_translations_incomplete"

    de = admin_client.post(
        f"/api/v1/document-templates/{template_id}/versions/",
        {
            "language": "de",
            "html": "<h1>Rechnung</h1>",
            "css": "",
            "page_settings": {"size": "A4"},
            "asset_keys": [],
        },
        format="json",
    )
    assert de.status_code == 201, de.json()
    published = admin_client.post(f"/api/v1/document-templates/{template_id}/publish/")
    assert published.status_code == 200, published.json()
    assert {v["language"] for v in published.json()["versions"] if v["status"] == "published"} == {
        "en",
        "de",
    }
    original = DocumentTemplateVersion.objects.get(pk=only_en.json()["id"])
    original.html = "changed"
    with pytest.raises(ValidationError):
        original.save()
    with pytest.raises(ValueError):
        DocumentTemplateVersion.objects.filter(pk=original.pk).update(html="changed")

    edited = admin_client.patch(
        f"/api/v1/document-templates/{template_id}/versions/{original.pk}/",
        {"html": "<h1>Updated receipt</h1>"},
        format="json",
    )
    assert edited.status_code == 200, edited.json()
    assert edited.json()["id"] != original.pk
    assert edited.json()["version"] == 2
    assert edited.json()["status"] == "draft"
    assert DocumentTemplateVersion.objects.get(pk=original.pk).html == "<h1>Receipt</h1>"
    assert AuditEvent.objects.filter(action_code="documents.template_published").count() == 1


def test_template_api_is_admin_only(admin_client: APIClient) -> None:
    template_id, _ = _create_pair(admin_client)
    for role in (UserRole.COMPANY_MEMBER, UserRole.READ_ONLY):
        user = User.objects.create_user(username=f"template-{role}", password="test", role=role)
        client = APIClient()
        client.force_authenticate(user=user)
        assert client.get("/api/v1/document-templates/").status_code == 403
        assert client.post(f"/api/v1/document-templates/{template_id}/publish/").status_code == 403


def test_asset_validation_rejects_unsafe_references_and_uploads(admin_client: APIClient) -> None:
    template_id, _ = _create_pair(admin_client)
    for key in ("/etc/passwd", "https://example.test/image.png", "../other/file.png"):
        response = admin_client.post(
            f"/api/v1/document-templates/{template_id}/versions/",
            {
                "language": "en",
                "html": "<h1>Invoice</h1>",
                "css": "",
                "page_settings": {"size": "A4"},
                "asset_keys": [key],
            },
            format="json",
        )
        assert response.status_code == 400, response.json()

    invalid = admin_client.post(
        f"/api/v1/document-templates/{template_id}/assets/",
        {
            "file": SimpleUploadedFile(
                "script.svg", b"<svg onload='alert(1)'/>", content_type="image/svg+xml"
            )
        },
        format="multipart",
    )
    assert invalid.status_code == 400
    large = admin_client.post(
        f"/api/v1/document-templates/{template_id}/assets/",
        {
            "file": SimpleUploadedFile(
                "large.png", BytesIO(b"x" * (2 * 1024 * 1024 + 1)).read(), content_type="image/png"
            )
        },
        format="multipart",
    )
    assert large.status_code == 400


def test_asset_keys_belong_to_template_and_published_selection_is_language_specific(
    admin_client: APIClient, tmp_path: Path
) -> None:
    from pinaks.apps.documents.services import get_published_version

    template_id, versions = _create_pair(admin_client)
    other_id = admin_client.post(
        "/api/v1/document-templates/", {"code": "other", "name": "Other"}, format="json"
    ).json()["id"]
    with override_settings(MEDIA_ROOT=tmp_path):
        uploaded = admin_client.post(
            f"/api/v1/document-templates/{template_id}/assets/",
            {
                "file": SimpleUploadedFile(
                    "logo.png", b"\x89PNG\r\n\x1a\nimage", content_type="image/png"
                )
            },
            format="multipart",
        )
        assert uploaded.status_code == 201, uploaded.json()
        key = uploaded.json()["key"]
        assert key.startswith(f"document-assets/{template_id}/")
        assert (tmp_path / key).exists()
        own = admin_client.patch(
            f"/api/v1/document-templates/{template_id}/versions/{versions['en']}/",
            {"asset_keys": [key]},
            format="json",
        )
        assert own.status_code == 200, own.json()
        foreign = admin_client.post(
            f"/api/v1/document-templates/{other_id}/versions/",
            {
                "language": "en",
                "html": "<h1>Other</h1>",
                "page_settings": {"size": "A4"},
                "asset_keys": [key],
            },
            format="json",
        )
        assert foreign.status_code == 400
    assert get_published_version(template_id=template_id, language="en") is None
    admin_client.post(f"/api/v1/document-templates/{template_id}/publish/")
    english = get_published_version(template_id=template_id, language="en")
    german = get_published_version(template_id=template_id, language="de")
    assert english is not None and english.asset_keys == [key]
    assert german is not None and german.asset_keys == []
