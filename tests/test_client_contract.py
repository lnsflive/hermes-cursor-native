from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "tests/scripts/client_contract_probe.py"
HERMES_SOURCE = Path("/root/.hermes/hermes-agent")
HERMES_PYTHON = HERMES_SOURCE / "venv/bin/python"


@pytest.mark.skipif(not HERMES_PYTHON.is_file(), reason="stock Hermes python not present")
def test_streaming_and_tool_contract_via_hermes_python() -> None:
    completed = subprocess.run(
        [str(HERMES_PYTHON), str(PROBE), str(HERMES_SOURCE)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout.strip())
    assert payload["streaming"] is True
    assert payload["tool_loop"] is True
