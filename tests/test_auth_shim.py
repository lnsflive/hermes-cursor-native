from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

HERMES_SOURCE = Path(os.getenv("HERMES_AGENT_ROOT", str(Path.home() / ".hermes" / "hermes-agent")))
HERMES_PYTHON = HERMES_SOURCE / (
    ".venv/bin/python" if (HERMES_SOURCE / ".venv/bin/python").exists() else "venv/bin/python"
)
HERMES_BIN = HERMES_SOURCE / "venv/bin/hermes"
PLUGIN_SRC = Path(__file__).resolve().parents[1] / "plugin" / "model-providers" / "cursor"


def _deploy_plugin(home: Path) -> Path:
    dest = home / "plugins" / "model-providers" / "cursor"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(PLUGIN_SRC, dest)
    return dest


def _run_hermes_python(script: str, *, home: Path, extra_env: dict[str, str] | None = None) -> dict:
    env = {"HOME": str(home), "HERMES_HOME": str(home), "PYTHONPATH": str(HERMES_SOURCE)}
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(
        [str(HERMES_PYTHON), "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return json.loads(completed.stdout.strip())


@pytest.mark.skipif(not HERMES_PYTHON.is_file(), reason="stock Hermes python not present")
def test_providers_first_discover_registers_cursor_in_auth_registry() -> None:
    with tempfile.TemporaryDirectory(prefix="cursor-auth-order-") as tmp:
        home = Path(tmp)
        _deploy_plugin(home)
        payload = _run_hermes_python(
            """
import json
import os
import sys
from pathlib import Path

home = Path(os.environ["HERMES_HOME"])
sys.path.insert(0, os.environ["PYTHONPATH"])

import providers as providers_mod
providers_mod._discover_providers()
import hermes_cli.auth as auth_mod

profile_registered = providers_mod.get_provider_profile("cursor") is not None
in_auth_registry = "cursor" in auth_mod.PROVIDER_REGISTRY
print(json.dumps({
    "profile_registered": profile_registered,
    "in_auth_registry": in_auth_registry,
}))
""",
            home=home,
        )
        assert payload["profile_registered"] is True
        assert payload["in_auth_registry"] is True


@pytest.mark.skipif(not HERMES_PYTHON.is_file(), reason="stock Hermes python not present")
def test_auth_first_import_then_discover_registers_cursor() -> None:
    with tempfile.TemporaryDirectory(prefix="cursor-auth-order-") as tmp:
        home = Path(tmp)
        payload = _run_hermes_python(
            f"""
import json
import os
import shutil
import sys
from pathlib import Path

home = Path(os.environ["HERMES_HOME"])
src = Path({json.dumps(str(PLUGIN_SRC))})
sys.path.insert(0, os.environ["PYTHONPATH"])

import hermes_cli.auth as auth_mod
before = "cursor" in auth_mod.PROVIDER_REGISTRY

dest = home / "plugins" / "model-providers" / "cursor"
dest.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(src, dest)

import providers as providers_mod
providers_mod._discovered = False
providers_mod._discover_providers()
after = "cursor" in auth_mod.PROVIDER_REGISTRY
print(json.dumps({{"before": before, "after": after}}))
""",
            home=home,
        )
        assert payload["before"] is False
        assert payload["after"] is True


@pytest.mark.skipif(not HERMES_PYTHON.is_file(), reason="stock Hermes python not present")
def test_auth_status_cursor_uses_registry_without_manual_registration() -> None:
    with tempfile.TemporaryDirectory(prefix="cursor-auth-status-") as tmp:
        home = Path(tmp)
        _deploy_plugin(home)
        completed = subprocess.run(
            [str(HERMES_BIN), "auth", "status", "cursor"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            env={"HERMES_HOME": str(home), "PYTHONPATH": str(HERMES_SOURCE)},
            cwd=HERMES_SOURCE,
        )
        assert completed.returncode == 0, completed.stderr
        text = f"{completed.stdout}\n{completed.stderr}".lower()
        assert "cursor" in text
        assert "logged out" in text or "logged in" in text
