"""Exercise the development bootstrap entry point without a database."""

import os
import subprocess
from pathlib import Path


def test_dev_bootstrap_migrates_and_seeds_without_printing_password(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    calls = tmp_path / "calls"
    uv = tmp_path / "uv"
    uv.write_text(
        "#!/bin/bash\n"
        'echo "$*" >> "$DEV_CALLS"\n'
        'if [[ "$*" == *bootstrap_admin* ]]; then\n'
        '  [[ "$PINAKS_BOOTSTRAP_ADMIN_USERNAME" == devadmin ]] || exit 1\n'
        '  [[ "$PINAKS_BOOTSTRAP_ADMIN_EMAIL" == devadmin@example.test ]] || exit 1\n'
        '  [[ "$PINAKS_BOOTSTRAP_ADMIN_PASSWORD" == "$EXPECTED_PASSWORD" ]] || exit 1\n'
        "fi\n"
    )
    uv.chmod(0o755)
    environment = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    for name in (
        "PINAKS_BOOTSTRAP_ADMIN_USERNAME",
        "PINAKS_BOOTSTRAP_ADMIN_EMAIL",
        "PINAKS_BOOTSTRAP_ADMIN_PASSWORD",
    ):
        environment.pop(name, None)
    password = "a long development password"
    result = subprocess.run(
        ["make", "dev-bootstrap"],
        cwd=root,
        env={**environment, "DEV_CALLS": str(calls), "EXPECTED_PASSWORD": password},
        input=f"{password}\n",
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text().splitlines() == [
        "run python backend/manage.py migrate",
        "run python backend/manage.py bootstrap_admin",
    ]
    assert password not in result.stdout + result.stderr
