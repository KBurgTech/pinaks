from rest_framework import serializers


class ApiRootSerializer(serializers.Serializer[dict[str, str]]):
    capabilities = serializers.URLField()
    probe = serializers.URLField()
    schema = serializers.URLField()


class ProbeSerializer(serializers.Serializer[dict[str, object]]):
    status = serializers.CharField()
    checks = serializers.ListField(child=serializers.CharField())


class CapabilitiesSerializer(serializers.Serializer[dict[str, object]]):
    role = serializers.ChoiceField(choices=("admin", "company_member", "read_only"))
    capabilities = serializers.DictField(child=serializers.BooleanField())
    features = serializers.DictField(child=serializers.BooleanField())


class ErrorItemSerializer(serializers.Serializer[dict[str, str]]):
    code = serializers.CharField()
    message = serializers.CharField()


class ErrorBodySerializer(serializers.Serializer[dict[str, object]]):
    code = serializers.CharField()
    message = serializers.CharField()
    # DRF's metaclass removes declared fields before class creation; the stubs
    # instead see the inherited runtime ``fields`` property at analysis time.
    fields = serializers.DictField(
        child=serializers.ListField(child=ErrorItemSerializer()),
    )  # type: ignore[assignment]


class ErrorEnvelopeSerializer(serializers.Serializer[dict[str, object]]):
    error = ErrorBodySerializer()
