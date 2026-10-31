"""Offline production-container smoke using a non-personal frozen snapshot."""

import json
import os
import sys
from pathlib import Path

import django


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pinaks.settings.test")
    django.setup()
    from pinaks.apps.e_invoicing.generation import HybridInvoiceGenerator

    # JSON is an external fixture boundary; the serializer validates its schema.
    snapshot = json.loads(Path(sys.argv[1]).read_text())
    if not isinstance(snapshot, dict):
        raise ValueError("Expected a snapshot object")
    result = HybridInvoiceGenerator().generate(snapshot)
    assert result.xml_report.valid and result.pdf_report.valid
    assert result.pdf and result.xml
    print("Frozen snapshot passed EN 16931, PDF/A-3 and package integrity checks")


if __name__ == "__main__":
    main()
