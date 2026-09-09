from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERMES_SOURCE = Path("/root/.hermes/hermes-agent")
HERMES_PYTHON = HERMES_SOURCE / "venv/bin/python"
PLUGIN_SRC = Path(__file__).resolve().parents[1] / "plugin" / "model-providers" / "cursor"


@pytest.mark.skipif(not HERMES_PYTHON.is_file(), reason="stock Hermes python not present")
def test_auth_shim_resolves_cursor_via_runtime_provider(monkeypatch) -> None:
    with tempfile.TemporaryDirectory(prefix="cursor-auth-shim-") as tmp:
        home = Path(tmp)
        plugin_dest = home / "plugins" / "model-providers" / "cursor"
        plugin_dest.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copytree(PLUGIN_SRC, plugin_dest)

        script = f"""
import json
import os
import sys
from pathlib import Path

home = Path({json.dumps(str(home))})
os.environ["HERMES_HOME"] = str(home)
sys.path.insert(0, {json.dumps(str(HERMES_SOURCE))})

import providers as providers_mod
providers_mod._discover_providers()
import hermes_cli.auth as auth_mod
for pp in providers_mod.list_providers():
    if pp.name not in auth_mod.PROVIDER_REGISTRY:
        auth_mod._register_plugin_provider(pp)

from hermes_cli.auth import resolve_api_key_provider_credentials

creds = resolve_api_key_provider_credentials("cursor")
registered = "cursor" in auth_mod.PROVIDER_REGISTRY
print(json.dumps({{
    "registered": registered,
    "has_key": bool(creds.get("api_key")),
    "source": creds.get("source", ""),
}}))
"""
        completed = subprocess.run(
            [str(HERMES_PYTHON), "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(completed.stdout.strip())
        assert payload["registered"] is True
        assert payload["has_key"] is False
        assert payload["source"] in {"", "default", "env"}
