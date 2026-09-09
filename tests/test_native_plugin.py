from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HERMES = Path(os.getenv("HERMES_AGENT_ROOT", str(Path.home() / ".hermes/hermes-agent")))
PYTHON = HERMES / (
    ".venv/bin/python" if (HERMES / ".venv/bin/python").exists() else "venv/bin/python"
)


@pytest.mark.skipif(not PYTHON.exists(), reason="Hermes integration runtime not available")
def test_native_flat_plugin_install_is_discovered(tmp_path):
    # This is the layout produced by `hermes plugins install`: repo root in
    # HERMES_HOME/plugins/<manifest-name>, not the legacy nested installer path.
    destination = tmp_path / "plugins/cursor"
    destination.mkdir(parents=True)
    for name in ("__init__.py", "plugin.yaml"):
        shutil.copyfile(REPO / name, destination / name)
    shutil.copytree(REPO / "plugin", destination / "plugin")
    script = """
import json
import hermes_cli.main as main
from providers import get_provider_profile
from hermes_cli.main_provider_setup import _build_provider_picker_rows
profile = get_provider_profile("cursor")
print(json.dumps({"registered": profile is not None,
 "visible": any(row[0] == "cursor" for row in _build_provider_picker_rows({}, "", {}, {})[0]),
 "oauth_flow": bool(getattr(main._model_flow_api_key_provider, "_cursor_flow_wrapper", False))}))
"""
    env = {"HOME": str(tmp_path), "HERMES_HOME": str(tmp_path), "PYTHONPATH": str(HERMES)}
    result = subprocess.run(
        [str(PYTHON), "-c", script], env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"registered": True, "visible": True, "oauth_flow": True}
