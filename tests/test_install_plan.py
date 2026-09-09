from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest

from hermes_cursor_native.capabilities import CapabilityReport
from hermes_cursor_native.cli import main
from hermes_cursor_native.discovery import Runtime
from hermes_cursor_native.install_plan import InstallBlockedError, build_install_plan
from hermes_cursor_native.manifest import InstallManifest


def _manifest() -> InstallManifest:
    return InstallManifest(
        version="0.2.0a1",
        artifacts={
            "windows-x64": {
                "filename": "cursor-sdk-bridge.exe",
                "sha256": "a" * 64,
                "url": "https://example.invalid/windows.exe",
            },
            "linux-x64": {
                "filename": "cursor-sdk-bridge",
                "sha256": "b" * 64,
                "url": "https://example.invalid/linux",
            },
        },
        bridge_version="1.0.27",
        plugin_commit="test",
    )


def _ready_capabilities() -> CapabilityReport:
    return CapabilityReport(
        runtime_id="posix-current",
        hermes_version="0.21.1",
        source_root=Path("/root/.hermes/hermes-agent"),
        plugin_seam=True,
        provider_client_seam=True,
        plugin_registered=True,
        client_contract=True,
    )


def _linux_runtime() -> Runtime:
    return Runtime(
        "posix-current",
        ("cli",),
        "linux",
        Path("/root/.hermes"),
        Path("/root/.hermes/hermes-agent"),
        Path("/root/.hermes/hermes-agent/venv/bin/hermes"),
        "0.21.1",
        True,
        "active",
    )


def test_plan_is_plugin_only_and_additive_by_default() -> None:
    plan = build_install_plan(
        runtime=_linux_runtime(),
        manifest=_manifest(),
        profile="default",
        architecture="x64",
        capability_report=_ready_capabilities(),
    )
    assert [operation.kind for operation in plan.operations] == [
        "backup",
        "plugin",
        "bridge",
        "configure",
        "oauth",
        "verify",
    ]
    assert plan.switch_default_model is False
    assert plan.run_oauth is False
    rendered = plan.to_json()
    assert "CURSOR_API_KEY" not in rendered
    assert "auth.json" not in rendered


def test_missing_capabilities_blocks_install() -> None:
    blocked = CapabilityReport(
        runtime_id="posix-current",
        hermes_version="0.21.1",
        source_root=Path("/root/.hermes/hermes-agent"),
        plugin_seam=False,
        provider_client_seam=False,
        plugin_registered=False,
        client_contract=False,
    )
    with pytest.raises(InstallBlockedError, match="not ready"):
        build_install_plan(
            runtime=_linux_runtime(),
            manifest=_manifest(),
            profile="default",
            architecture="x64",
            capability_report=blocked,
        )


def test_wsl_uses_linux_artifact() -> None:
    runtime = Runtime(
        "wsl:Ubuntu",
        ("cli",),
        "wsl",
        PurePosixPath("/home/test/.hermes"),
        PurePosixPath("/home/test/.hermes/hermes-agent"),
        PurePosixPath("/home/test/.local/bin/hermes"),
        "0.21.1",
        True,
        "available",
    )
    plan = build_install_plan(
        runtime=runtime,
        manifest=_manifest(),
        profile="default",
        architecture="x64",
        capability_report=_ready_capabilities(),
    )
    assert plan.artifact_key == "linux-x64"


def test_cli_install_dry_run_emits_plan_without_applying(capsys, monkeypatch) -> None:
    runtime = _linux_runtime()
    applied = []
    monkeypatch.setattr(
        "hermes_cursor_native.install_plan.probe_runtime",
        lambda _runtime: _ready_capabilities(),
    )
    exit_code = main(
        ["install", "--dry-run", "--json", "--runtime", "posix-current"],
        discover=lambda: [runtime],
        manifest_loader=lambda _path: _manifest(),
        architecture=lambda: "x64",
        apply_plan=lambda plan: applied.append(plan),
    )
    assert exit_code == 0
    assert applied == []
    payload = json.loads(capsys.readouterr().out)
    assert payload["capabilities"]["plugin_ready"] is True
