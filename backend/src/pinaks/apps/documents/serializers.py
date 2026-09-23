from rest_framework import serializers

from pinaks.apps.documents.models import DocumentAsset, DocumentTemplate, DocumentTemplateVersion


class TemplateWriteSerializer(serializers.Serializer[dict[str, object]]):
    code = serializers.SlugField(max_length=80)
    name = serializers.CharField(max_length=120)


class TemplateVersionWriteSerializer(serializers.Serializer[dict[str, object]]):
    language = serializers.ChoiceField(choices=("en", "de"), required=False)
    html = serializers.CharField(allow_blank=True, required=False)
    css = serializers.CharField(allow_blank=True, required=False)
    page_settings = serializers.JSONField(required=False)
    asset_keys = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )


class TemplateVersionSerializer(serializers.ModelSerializer[DocumentTemplateVersion]):
    class Meta:
        model = DocumentTemplateVersion
        fields = (
            "id",
            "language",
            "version",
            "status",
            "html",
            "css",
            "page_settings",
            "asset_keys",
            "created_at",
            "created_by",
            "published_at",
            "published_by",
        )
        read_only_fields = fields


class TemplateSerializer(serializers.ModelSerializer[DocumentTemplate]):
    versions = TemplateVersionSerializer(many=True, read_only=True)

    class Meta:
        model = DocumentTemplate
        fields = ("id", "code", "name", "created_at", "versions")
        read_only_fields = fields


class DocumentAssetSerializer(serializers.ModelSerializer[DocumentAsset]):
    class Meta:
        model = DocumentAsset
        fields = ("id", "key", "content_type", "size", "created_at")
        read_only_fields = fields


class AssetUploadSerializer(serializers.Serializer[dict[str, object]]):
    file = serializers.FileField()


class PreviewRequestSerializer(serializers.Serializer[dict[str, object]]):
    language = serializers.ChoiceField(choices=("en", "de"))
    invoice_id = serializers.IntegerField(min_value=1, required=False)
    format = serializers.ChoiceField(choices=("html", "pdf"), default="pdf")


class PreviewResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField(read_only=True)
    url = serializers.CharField(read_only=True)
    expires_at = serializers.DateTimeField(read_only=True)
