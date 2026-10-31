from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader

from pinaks.apps.e_invoicing.generation import HybridInvoiceGenerator
from pinaks.apps.e_invoicing.mustang import MustangValidator
from test_e_invoicing import JAVA_EXECUTABLE, MUSTANG_CLI_JAR
from test_snapshot_pdf import visual_snapshot


@pytest.mark.parametrize("language", ["en", "de"])
@pytest.mark.parametrize("exempt", [False, True])
def test_generate_validated_hybrid_from_frozen_snapshot(language: str, exempt: bool) -> None:
    frozen = visual_snapshot(language, exempt)
    before = deepcopy(frozen)
    result = HybridInvoiceGenerator(
        validator=MustangValidator(jar_path=MUSTANG_CLI_JAR, java_executable=JAVA_EXECUTABLE)
    ).generate(frozen)

    assert PdfReader(BytesIO(result.pdf)).attachments["factur-x.xml"] == [result.xml]
    assert result.xml_report.valid and result.pdf_report.valid
    assert result.xml_report.validator == result.pdf_report.validator == "Mustang 2.23.0"
    assert b"flavour=3b" in result.pdf_report.raw_report
    assert result.standard == "Factur-X"
    assert result.profile == "EN 16931"
    assert result.specification_version == "1.09"
    assert result.visual.template_version_id == 42
    assert frozen == before


@pytest.mark.parametrize(
    ("stage", "code", "retryable"),
    [
        ("mapping", "mapping_failed", False),
        ("renderer", "visual_render_failed", False),
        ("packaging", "packaging_failed", False),
        ("xml", "xml_validation_failed", False),
        ("pdf", "pdf_validation_failed", False),
        ("tool", "validator_unavailable", True),
        ("timeout", "validator_unavailable", True),
        ("storage", "visual_render_unavailable", True),
    ],
)
def test_generation_failure_is_sanitized_and_classified(
    stage: str, code: str, retryable: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from pinaks.apps.documents.snapshot_renderer import SnapshotRenderError
    from pinaks.apps.e_invoicing.contracts import ValidationReport
    from pinaks.apps.e_invoicing.generation import GenerationError
    from pinaks.apps.e_invoicing.mustang import ValidatorExecutionError
    from pinaks.apps.e_invoicing.snapshot import InvoiceMappingError

    generator = HybridInvoiceGenerator()

    def fail(*args: object, **kwargs: object) -> bytes:
        if stage == "mapping":
            raise InvoiceMappingError("invalid_snapshot")
        if stage == "renderer":
            raise SnapshotRenderError()
        if stage == "storage":
            raise SnapshotRenderError() from OSError("private path")
        raise ValueError("private invoice content")

    def validate(document: bytes, *, filename: str) -> ValidationReport:
        if stage == "tool":
            raise ValidatorExecutionError("private provider output")
        if stage == "timeout":
            raise subprocess.TimeoutExpired("private command", 1)
        valid = (stage, filename) not in {("xml", "invoice.xml"), ("pdf", "invoice.pdf")}
        return ValidationReport(valid, "External fake validator", b"<report/>", ())

    monkeypatch.setattr(generator.validator, "validate", validate)
    if stage == "mapping":
        monkeypatch.setattr(generator.serializer, "serialize", fail)
    elif stage in {"renderer", "storage"}:
        monkeypatch.setattr(generator.renderer, "render", fail)
    elif stage == "packaging":
        monkeypatch.setattr(generator.packager, "package", fail)
    with pytest.raises(GenerationError) as error:
        generator.generate(visual_snapshot())
    assert error.value.code == code
    assert error.value.retryable is retryable
    assert str(error.value) == code
    if stage in {"xml", "pdf"}:
        assert error.value.report is not None
        assert not error.value.report.valid


@pytest.mark.parametrize("damage", ["corrupt_pdf", "attachment_metadata", "xml_total"])
def test_real_validator_rejects_damaged_artifacts(
    damage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject

    from pinaks.apps.e_invoicing.generation import GenerationError

    generator = HybridInvoiceGenerator(
        validator=MustangValidator(jar_path=MUSTANG_CLI_JAR, java_executable=JAVA_EXECUTABLE)
    )
    package = generator.packager.package
    serialize = generator.serializer.serialize

    def damaged_package(source_pdf: bytes, invoice_xml: bytes, *, language: str) -> bytes:
        if damage == "corrupt_pdf":
            return b"%PDF-broken"
        pdf = package(source_pdf, invoice_xml, language=language)
        writer = PdfWriter(clone_from=BytesIO(pdf))
        associated = writer.root_object["/AF"]
        assert isinstance(associated, ArrayObject)
        attachment = associated[0].get_object()
        assert isinstance(attachment, DictionaryObject)
        attachment[NameObject("/AFRelationship")] = NameObject("/Unspecified")
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    def damaged_xml(snapshot: object) -> bytes:
        assert isinstance(snapshot, dict)
        xml = serialize(snapshot)
        changed = xml.replace(b"<ram:DuePayableAmount>238.00<", b"<ram:DuePayableAmount>239.00<")
        assert changed != xml
        return changed

    if damage == "xml_total":
        monkeypatch.setattr(generator.serializer, "serialize", damaged_xml)
    else:
        monkeypatch.setattr(generator.packager, "package", damaged_package)
    with pytest.raises(GenerationError) as error:
        generator.generate(visual_snapshot())
    assert error.value.code == (
        "xml_validation_failed" if damage == "xml_total" else "pdf_validation_failed"
    )
    assert error.value.report is not None
    assert not error.value.report.valid


def test_packaged_xml_must_match_generated_xml(monkeypatch: pytest.MonkeyPatch) -> None:
    from pinaks.apps.e_invoicing.generation import GenerationError

    generator = HybridInvoiceGenerator(
        validator=MustangValidator(jar_path=MUSTANG_CLI_JAR, java_executable=JAVA_EXECUTABLE)
    )
    package = generator.packager.package

    def substitute(source_pdf: bytes, invoice_xml: bytes, *, language: str) -> bytes:
        return package(
            source_pdf, invoice_xml.replace(b"INV-2026-0001", b"INV-2026-9999"), language=language
        )

    monkeypatch.setattr(generator.packager, "package", substitute)
    with pytest.raises(GenerationError) as error:
        generator.generate(visual_snapshot())
    assert error.value.code == "pdf_validation_failed"
