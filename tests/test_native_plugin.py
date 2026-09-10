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


@pytest.mark.skipif(not PYTHON.exists(), reason="Hermes integration runtime not available")
@pytest.mark.parametrize("profile", ["default", "work"])
@pytest.mark.parametrize("mode", ["configured", "env", "path", "wheel", "managed", "absent"])
def test_status_uses_native_resolver(tmp_path, monkeypatch, profile, mode):
    import hermes_cursor_native.verify as verify
    from hermes_cursor_native.discovery import Runtime

    home = tmp_path / "home"
    selected = home if profile == "default" else home / "profiles" / profile
    destination = selected / "plugins/cursor"
    destination.mkdir(parents=True)
    for name in ("__init__.py", "plugin.yaml"):
        shutil.copyfile(REPO / name, destination / name)
    shutil.copytree(REPO / "plugin", destination / "plugin")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "unrelated"))
    monkeypatch.delenv("CURSOR_SDK_BRIDGE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "path"))
    name = "cursor-sdk-bridge.exe" if os.name == "nt" else "cursor-sdk-bridge"
    launcher = tmp_path / "external" / name
    if mode == "managed":
        launcher = selected / "cursor-sdk-bridge/bin" / name
    elif mode == "path":
        launcher = tmp_path / "path" / name
    elif mode == "wheel":
        launcher = tmp_path / "wheels/cursor_sdk/bridge/bin" / name
    if mode != "absent":
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\nexit 99\n")
        launcher.chmod(0o755)
    if mode == "configured":
        (selected / "config.yaml").write_text(
            "cursor_bridge:\n  command: " + json.dumps(str(launcher)) + "\n"
        )
    if mode == "env":
        monkeypatch.setenv("CURSOR_SDK_BRIDGE_BIN", str(launcher))
    # Isolate optional SDK wheel discovery from whatever is installed on the host.
    wheel = tmp_path / "wheels/cursor_sdk"
    wheel.mkdir(parents=True, exist_ok=True)
    (wheel / "__init__.py").touch()
    real_run = subprocess.run

    def run(args, **kwargs):
        assert kwargs["env"]["HERMES_HOME"] == str(selected)
        script = "import sys; sys.path.insert(0, " + repr(str(wheel.parent)) + ");\n" + args[2]
        return real_run([args[0], args[1], script], **kwargs)

    monkeypatch.setattr(verify.subprocess, "run", run)
    monkeypatch.setattr(verify, "resolve_hermes_python", lambda _: PYTHON)
    runtime = Runtime("test", ("cli",), "linux", home, HERMES, PYTHON.parent / "hermes",
                      "test", True, "active")
    bridge, notes = verify.resolve_status_bridge(runtime, profile)
    assert bridge == (None if mode == "absent" else launcher.resolve()), notes
    assert notes == (("bridge resolver found no launcher",) if mode == "absent" else ())
