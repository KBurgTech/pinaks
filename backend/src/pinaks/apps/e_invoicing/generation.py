"""Generate validated artifacts from one frozen snapshot without finalizing issuance."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from io import BytesIO
from subprocess import SubprocessError

from pypdf import PdfReader
from pypdf.errors import PyPdfError
from pypdf.generic import ArrayObject, DictionaryObject

from pinaks.apps.documents.snapshot_renderer import (
    SnapshotRenderError,
    VisualDocument,
    VisualDocumentRenderer,
    WeasyPrintRenderer,
)
from pinaks.apps.e_invoicing.contracts import (
    EInvoiceSerializer,
    EInvoiceValidator,
    HybridPdfPackager,
    ValidationFinding,
    ValidationReport,
)
from pinaks.apps.e_invoicing.facturx import FacturXHybridPdfPackager, FacturXSerializer
from pinaks.apps.e_invoicing.mustang import MustangValidator, ValidatorExecutionError
from pinaks.apps.e_invoicing.snapshot import InvoiceMappingError, obj, string


@dataclass(frozen=True, slots=True)
class GeneratedInvoice:
    pdf: bytes
    xml: bytes
    xml_report: ValidationReport
    pdf_report: ValidationReport
    visual: VisualDocument
    standard: str = FacturXSerializer.standard
    profile: str = FacturXSerializer.profile
    specification_version: str = FacturXSerializer.specification_version


class GenerationError(RuntimeError):
    """Safe worker-facing failure; detailed validation evidence stays in the report."""

    def __init__(
        self, code: str, *, retryable: bool = False, report: ValidationReport | None = None
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.report = report
        super().__init__(code)


def _verify_package(pdf: bytes, xml: bytes, report: ValidationReport) -> None:
    try:
        reader = PdfReader(BytesIO(pdf), strict=True)
        root = reader.trailer["/Root"]
        if not isinstance(root, DictionaryObject):
            raise ValueError
        associated = root.get("/AF")
        if associated is None:
            raise ValueError
        associated = associated.get_object()
        if not isinstance(associated, ArrayObject) or len(associated) != 1:
            raise ValueError
        attachment = associated[0].get_object()
        if (
            not isinstance(attachment, DictionaryObject)
            or attachment.get("/AFRelationship") != "/Data"
            or attachment.get("/F") != "factur-x.xml"
            or attachment.get("/UF") != "factur-x.xml"
            or list(reader.attachments) != ["factur-x.xml"]
            or reader.attachments["factur-x.xml"] != [xml]
        ):
            raise ValueError
    except (PyPdfError, ValueError, KeyError, TypeError) as error:
        failed = replace(
            report,
            valid=False,
            findings=(
                *report.findings,
                ValidationFinding("error", "package_integrity", "Invalid XML attachment package"),
            ),
        )
        raise GenerationError("pdf_validation_failed", report=failed) from error


class HybridInvoiceGenerator:
    def __init__(
        self,
        *,
        serializer: EInvoiceSerializer | None = None,
        renderer: VisualDocumentRenderer | None = None,
        packager: HybridPdfPackager | None = None,
        validator: EInvoiceValidator | None = None,
    ) -> None:
        self.serializer = serializer or FacturXSerializer()
        self.renderer = renderer or WeasyPrintRenderer()
        self.packager = packager or FacturXHybridPdfPackager()
        self.validator = validator or MustangValidator()

    def _validate(self, document: bytes, *, filename: str) -> ValidationReport:
        try:
            report = self.validator.validate(document, filename=filename)
        except (ValidatorExecutionError, OSError, SubprocessError) as error:
            raise GenerationError("validator_unavailable", retryable=True) from error
        if not report.valid:
            code = "xml_validation_failed" if filename.endswith(".xml") else "pdf_validation_failed"
            raise GenerationError(code, report=report)
        return report

    def generate(self, snapshot: Mapping[str, object]) -> GeneratedInvoice:
        try:
            xml = self.serializer.serialize(snapshot)
            language = string(obj(snapshot.get("invoice")).get("language"))
        except (InvoiceMappingError, ValueError) as error:
            raise GenerationError("mapping_failed") from error
        xml_report = self._validate(xml, filename="invoice.xml")
        try:
            visual = self.renderer.render(snapshot)
        except SnapshotRenderError as error:
            if isinstance(error.__cause__, OSError):
                raise GenerationError("visual_render_unavailable", retryable=True) from error
            raise GenerationError("visual_render_failed") from error
        except OSError as error:
            raise GenerationError("visual_render_unavailable", retryable=True) from error
        try:
            pdf = self.packager.package(visual.pdf, xml, language=language)
        except (ValueError, OSError) as error:
            raise GenerationError("packaging_failed") from error
        pdf_report = self._validate(pdf, filename="invoice.pdf")
        _verify_package(pdf, xml, pdf_report)
        return GeneratedInvoice(pdf, xml, xml_report, pdf_report, visual)
