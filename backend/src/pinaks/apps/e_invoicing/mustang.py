import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from pinaks.apps.e_invoicing.contracts import ValidationFinding, ValidationReport

DEFAULT_MUSTANG_JAR = Path("/opt/pinaks/mustang/Mustang-CLI-2.23.0.jar")


class ValidatorExecutionError(RuntimeError):
    """The pinned validator could not produce a machine-readable report."""


class MustangValidator:
    """Run Mustang's embedded EN 16931 and veraPDF validators offline."""

    def __init__(
        self,
        *,
        jar_path: Path | None = None,
        java_executable: str | Path = "java",
        timeout_seconds: int = 60,
    ) -> None:
        configured_path = os.environ.get("MUSTANG_CLI_JAR")
        self.jar_path = jar_path or (
            Path(configured_path) if configured_path else DEFAULT_MUSTANG_JAR
        )
        self.java_executable = str(java_executable)
        self.timeout_seconds = timeout_seconds

    def validate(self, document: bytes, *, filename: str) -> ValidationReport:
        safe_filename = Path(filename).name
        if safe_filename != filename or Path(safe_filename).suffix.lower() not in {".xml", ".pdf"}:
            raise ValueError("filename must be a plain .xml or .pdf filename")
        if not self.jar_path.is_file():
            raise ValidatorExecutionError(f"Mustang CLI is not installed at {self.jar_path}")

        with TemporaryDirectory(prefix="pinaks-einvoice-") as directory:
            document_path = Path(directory) / safe_filename
            document_path.write_bytes(document)
            completed = subprocess.run(
                [
                    self.java_executable,
                    "-Djava.awt.headless=true",
                    "-jar",
                    str(self.jar_path),
                    "--action",
                    "validate",
                    "--source",
                    str(document_path),
                    "--no-notices",
                    "--disable-file-logging",
                ],
                check=False,
                capture_output=True,
                timeout=self.timeout_seconds,
            )

        try:
            root = ElementTree.fromstring(completed.stdout)
        except ElementTree.ParseError as error:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise ValidatorExecutionError(
                f"Mustang did not return an XML report (exit {completed.returncode}): {detail}"
            ) from error

        summary = root.find("./summary")
        valid = summary is not None and summary.get("status") == "valid"
        validator_element = root.find(".//validator")
        version = validator_element.get("version") if validator_element is not None else "unknown"
        findings = tuple(
            ValidationFinding(
                level=element.tag,
                code=element.get("code", element.get("type", "unknown")),
                message=" ".join("".join(element.itertext()).split()),
            )
            for element in root.iter()
            if element.tag in {"error", "warning"}
        )
        valid = valid and all(finding.level != "error" for finding in findings)
        return ValidationReport(
            valid=valid,
            validator=f"Mustang {version}",
            raw_report=completed.stdout,
            findings=findings,
        )
