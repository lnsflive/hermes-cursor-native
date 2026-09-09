from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest

from hermes_cursor_native.cli import main
from hermes_cursor_native.discovery import Runtime
from hermes_cursor_native.capabilities import CapabilityReport
from hermes_cursor_native.install_plan import (
    GitState,
    InstallBlockedError,
    InstallManifest,
    build_install_plan,
)


def _manifest() -> InstallManifest:
    return InstallManifest(
        version="0.1.0a1",
        supported_hermes=("0.20.5",),
        base_commits=("9ddb6547",),
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
        patch_series=("0001-cursor-provider.patch", "0002-windows.patch"),
    )


def _windows_runtime() -> Runtime:
    return Runtime(
        "windows-current",
        ("cli", "desktop"),
        "windows",
        Path("C:/Hermes"),
        Path("C:/Hermes/hermes-agent"),
        Path("C:/Hermes/hermes-agent/venv/Scripts/hermes.exe"),
        "0.20.5",
        True,
        "active",
    )


def _patch_capabilities() -> CapabilityReport:
    return CapabilityReport(
        runtime_id="windows-current",
        hermes_version="0.20.5",
        source_root=Path("C:/Hermes/hermes-agent"),
        plugin_seam=False,
        provider_supplied_client=False,
        streaming_sdkbridge_rail=False,
        cursor_bridge_config=False,
    )


def _plugin_capabilities() -> CapabilityReport:
    return CapabilityReport(
        runtime_id="posix-current",
        hermes_version="0.21.1",
        source_root=Path("/root/.hermes/hermes-agent"),
        plugin_seam=True,
        provider_supplied_client=True,
        streaming_sdkbridge_rail=False,
        cursor_bridge_config=True,
    )


def test_plan_contains_explicit_ordered_operations_without_secrets() -> None:
    plan = build_install_plan(
        runtime=_windows_runtime(),
        manifest=_manifest(),
        profile="default",
        git_state=GitState(clean=True, branch="main", head="9ddb6547"),
        architecture="x64",
        capability_report=_patch_capabilities(),
    )

    assert plan.install_mode == "patch"
    assert [operation.kind for operation in plan.operations] == [
        "backup",
        "branch",
        "patch",
        "bridge",
        "configure",
        "oauth",
        "verify",
    ]
    assert plan.artifact_key == "windows-x64"
    assert plan.requires_approval is True
    rendered = plan.to_json()
    assert "CURSOR_API_KEY" not in rendered
    assert "auth.json" not in rendered


def test_dirty_checkout_blocks_install() -> None:
    with pytest.raises(InstallBlockedError, match="dirty"):
        build_install_plan(
            runtime=_windows_runtime(),
            manifest=_manifest(),
            profile="default",
            git_state=GitState(clean=False, branch="main", head="9ddb6547"),
            architecture="x64",
            capability_report=_patch_capabilities(),
        )


def test_missing_capabilities_blocks_install() -> None:
    runtime = Runtime(
        **{**_windows_runtime().__dict__, "version": "0.19.0"},
    )

    with pytest.raises(InstallBlockedError, match="lacks required Cursor provider interfaces"):
        build_install_plan(
            runtime=runtime,
            manifest=_manifest(),
            profile="default",
            git_state=GitState(clean=True, branch="main", head="old"),
            architecture="x64",
            capability_report=_patch_capabilities(),
        )


def test_plugin_mode_plan_uses_user_plugin_operations() -> None:
    runtime = Runtime(
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
    plan = build_install_plan(
        runtime=runtime,
        manifest=_manifest(),
        profile="default",
        git_state=None,
        architecture="x64",
        capability_report=_plugin_capabilities(),
    )
    assert plan.install_mode == "plugin"
    assert plan.operations[1].kind == "plugin"
    assert any(operation.kind == "note" for operation in plan.operations)


def test_unrecognized_base_commit_blocks_fresh_patch_install() -> None:
    with pytest.raises(InstallBlockedError, match="base commit"):
        build_install_plan(
            runtime=_windows_runtime(),
            manifest=_manifest(),
            profile="default",
            git_state=GitState(clean=True, branch="main", head="unrelated"),
            architecture="x64",
            capability_report=_patch_capabilities(),
        )


def test_maintained_deployment_branch_can_be_reconfigured_after_upstream_merge() -> None:
    plan = build_install_plan(
        runtime=_windows_runtime(),
        manifest=_manifest(),
        profile="default",
        git_state=GitState(
            clean=True,
            branch="cursor-provider-deployed",
            head="post-merge-head",
        ),
        architecture="x64",
        provider_installed=True,
        capability_report=_patch_capabilities(),
    )

    assert plan.runtime.runtime_id == "windows-current"


def test_maintained_branch_without_valid_provider_proof_is_blocked() -> None:
    with pytest.raises(InstallBlockedError, match="provider validation"):
        build_install_plan(
            runtime=_windows_runtime(),
            manifest=_manifest(),
            profile="default",
            git_state=GitState(
                clean=True,
                branch="cursor-provider-deployed",
                head="post-merge-head",
            ),
            architecture="x64",
            provider_installed=False,
            capability_report=_patch_capabilities(),
        )


def test_legacy_data_only_runtime_blocks_install() -> None:
    legacy = Runtime(
        "windows-legacy",
        ("legacy",),
        "windows",
        Path("C:/Users/test/.hermes"),
        None,
        None,
        "",
        False,
        "legacy/inactive",
    )

    with pytest.raises(InstallBlockedError, match="not usable"):
        build_install_plan(
            runtime=legacy,
            manifest=_manifest(),
            profile="default",
            git_state=None,
            architecture="x64",
        )


def test_wsl_uses_linux_artifact_and_posix_paths() -> None:
    runtime = Runtime(
        "wsl:Ubuntu",
        ("cli",),
        "wsl",
        PurePosixPath("/home/test/.hermes"),
        PurePosixPath("/home/test/.hermes/hermes-agent"),
        PurePosixPath("/home/test/.local/bin/hermes"),
        "0.20.5",
        True,
        "available",
    )

    plan = build_install_plan(
        runtime=runtime,
        manifest=_manifest(),
        profile="research",
        git_state=GitState(clean=True, branch="main", head="9ddb6547"),
        architecture="x64",
        capability_report=_patch_capabilities(),
    )

    assert plan.artifact_key == "linux-x64"
    assert str(plan.runtime.home) == "/home/test/.hermes"


def test_missing_platform_artifact_blocks_install() -> None:
    with pytest.raises(InstallBlockedError, match="windows-arm64"):
        build_install_plan(
            runtime=_windows_runtime(),
            manifest=_manifest(),
            profile="default",
            git_state=GitState(clean=True, branch="main", head="9ddb6547"),
            architecture="arm64",
            capability_report=_patch_capabilities(),
        )


def test_cli_install_dry_run_emits_plan_without_applying(capsys) -> None:
    runtime = _windows_runtime()
    applied = []

    exit_code = main(
        [
            "install",
            "--dry-run",
            "--json",
            "--runtime",
            "windows-current",
            "--profile",
            "default",
        ],
        discover=lambda: [runtime],
        manifest_loader=lambda _path: _manifest(),
        git_probe=lambda _root: GitState(clean=True, branch="main", head="9ddb6547"),
        architecture=lambda: "x64",
        apply_plan=lambda plan: applied.append(plan),
    )

    assert exit_code == 0
    assert applied == []
    payload = json.loads(capsys.readouterr().out)
    assert payload["runtime"]["runtime_id"] == "windows-current"
    assert payload["operations"][-1]["kind"] == "verify"


def test_cli_apply_requires_approval_and_noninteractive_target() -> None:
    runtime = _windows_runtime()
    applied = []
    common = {
        "discover": lambda: [runtime],
        "manifest_loader": lambda _path: _manifest(),
        "git_probe": lambda _root: GitState(clean=True, branch="main", head="9ddb6547"),
        "architecture": lambda: "x64",
        "apply_plan": lambda plan: applied.append(plan),
    }

    assert (
        main(
            ["install", "--runtime", "windows-current"],
            input_func=lambda _p: "n",
            **common,
        )
        == 1
    )
    assert applied == []
    assert (
        main(
            ["install", "--runtime", "windows-current"],
            input_func=lambda _p: "y",
            **common,
        )
        == 0
    )
    assert len(applied) == 1

    applied.clear()
    with pytest.raises(RuntimeError, match="explicit --runtime"):
        main(["install", "--yes"], **common)
    assert main(["install", "--yes", "--runtime", "windows-current"], **common) == 0
    assert len(applied) == 1


def test_missing_named_profile_is_never_created_by_install_planning() -> None:
    with pytest.raises(InstallBlockedError, match="does not exist"):
        build_install_plan(
            runtime=_windows_runtime(),
            manifest=_manifest(),
            profile="cursorbot",
            git_state=GitState(clean=True, branch="main", head="9ddb6547"),
            architecture="x64",
            profile_exists=False,
            capability_report=_patch_capabilities(),
        )
