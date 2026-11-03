"""Exercise the development launcher with external commands replaced by stubs."""

import os
import subprocess
from pathlib import Path


def test_dev_stops_servers_when_one_exits(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    calls = tmp_path / "calls"
    uv = tmp_path / "uv"
    uv.write_text(
        "#!/bin/bash\n"
        'echo "$*" >> "$DEV_CALLS"\n'
        'if [[ "$*" == *migrate* ]]; then exit 0; fi\n'
        'while [[ ! -f "$DEV_READY" ]]; do sleep 0.05; done\n'
        "exit 7\n"
    )
    corepack = tmp_path / "corepack"
    corepack.write_text(
        "#!/bin/bash\n"
        'echo "$*" >> "$DEV_CALLS"\n'
        "trap 'echo stopped >> \"$DEV_CALLS\"; exit 0' TERM\n"
        'touch "$DEV_READY"\n'
        "while true; do sleep 0.05; done\n"
    )
    uv.chmod(0o755)
    corepack.chmod(0o755)
    result = subprocess.run(
        ["make", "dev"],
        cwd=root,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "DEV_CALLS": str(calls),
            "DEV_READY": str(tmp_path / "ready"),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert calls.exists(), result.stderr
    commands = calls.read_text().splitlines()
    assert commands[0] == "run python backend/manage.py migrate"
    assert "run python backend/manage.py runserver 0.0.0.0:8000" in commands
    assert "pnpm --filter @pinaks/web dev --host 0.0.0.0" in commands
    assert "stopped" in commands
    assert result.returncode != 0
