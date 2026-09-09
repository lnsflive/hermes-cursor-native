from __future__ import annotations

import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from hermes_cursor_native.capabilities import probe_runtime, resolve_hermes_python
from hermes_cursor_native.discovery import Runtime

HERMES_SOURCE = Path(os.getenv("HERMES_AGENT_ROOT", str(Path.home() / ".hermes/hermes-agent")))


@pytest.mark.skipif(not HERMES_SOURCE.is_dir(), reason="stock Hermes checkout not present")
def test_live_stock_hermes_passes_behavioral_capability_probe() -> None:
    runtime = Runtime(
        "posix-current",
        ("cli",),
        "linux",
        Path.home() / ".hermes",
        HERMES_SOURCE,
        HERMES_SOURCE
        / (
            ".venv/bin/hermes"
            if (HERMES_SOURCE / ".venv/bin/hermes").exists()
            else "venv/bin/hermes"
        ),
        "0.21.1",
        True,
        "active",
    )
    report = probe_runtime(runtime)
    assert report.plugin_seam is True
    assert report.provider_client_seam is True
    assert report.plugin_registered is True
    assert report.client_contract is True
    assert report.plugin_ready is True


@pytest.mark.parametrize("layout", ["venv/Scripts", ".venv/Scripts", "venv/bin", ".venv/bin"])
@pytest.mark.parametrize("wrapper", [False, True])
def test_resolve_runtime_python(tmp_path: Path, layout: str, wrapper: bool) -> None:
    windows = "Scripts" in layout
    directory = tmp_path / layout
    directory.mkdir(parents=True)
    python = directory / ("python.exe" if windows else "python")
    python.touch()
    executable = directory / ("hermes.exe" if windows else "hermes")
    executable.touch()
    if wrapper:
        executable = tmp_path / "hermes-wrapper"
        executable.touch()
    runtime = Runtime(
        "test", ("cli",), "windows" if windows else "linux",
        tmp_path / "home", tmp_path, executable, "test", True, "active",
    )
    assert resolve_hermes_python(runtime) == python
    python.unlink()
    assert resolve_hermes_python(runtime) is None
    assert resolve_hermes_python(replace(runtime, source_root=None, executable=None)) is None


@pytest.mark.skipif(not HERMES_SOURCE.is_dir(), reason="stock Hermes checkout not present")
@pytest.mark.parametrize("state", ["absent", "corrupt", "valid"])
def test_deployed_probe_uses_selected_profile(tmp_path, monkeypatch, state):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    home = tmp_path / "estate"
    selected = home / "profiles/work"
    plugin_source = Path(__file__).resolve().parents[1] / "plugin/model-providers/cursor"
    # A healthy default-profile plugin must not mask a missing/broken selected plugin.
    shutil.copytree(plugin_source, home / "plugins/model-providers/cursor")
    deployed = selected / "plugins/model-providers/cursor"
    if state != "absent":
        shutil.copytree(plugin_source, deployed)
        if state == "corrupt":
            (deployed / "__init__.py").write_text("raise RuntimeError('broken deployed plugin')")
    executable = HERMES_SOURCE / ".venv/bin/hermes"
    if not executable.exists():
        executable = HERMES_SOURCE / "venv/bin/hermes"
    runtime = Runtime("test", ("cli",), "linux", home, HERMES_SOURCE, executable,
                      "test", True, "active")
    report = probe_runtime(runtime, hermes_home=selected, deployed=True)
    assert report.interface_ready
    assert report.plugin_registered is (state == "valid")
    assert report.client_contract is (state == "valid")
    assert deployed.exists() is (state != "absent")
