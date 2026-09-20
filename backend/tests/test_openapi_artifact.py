import json
from pathlib import Path

from drf_spectacular.generators import SchemaGenerator


def test_committed_openapi_artifact_matches_runtime_schema() -> None:
    artifact_path = Path(__file__).parents[1] / "schema" / "openapi.json"
    committed_schema = json.loads(artifact_path.read_text(encoding="utf-8"))
    runtime_schema = SchemaGenerator().get_schema(public=True)

    assert committed_schema == runtime_schema
