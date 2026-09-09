from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from hermes_cursor_native.capabilities import CapabilityReport
from hermes_cursor_native.discovery import Runtime
from hermes_cursor_native.install_plan import build_install_plan
from hermes_cursor_native.installer import (
    ApprovalRequiredError,
    CommandResult,
    deploy_plugin,
    execute_install_plan,
    require_approval,
    safe_extract_tar,
    verify_sha256,
)
from hermes_cursor_native.manifest import InstallManifest
from hermes_cursor_native.verify import InstallReceipt


def test_require_approval_blocks_unapproved_install() -> None:
    with pytest.raises(ApprovalRequiredError):
        require_approval(False)


def test_verify_sha256_detects_mismatch() -> None:
    with pytest.raises(Exception, match="SHA256 mismatch"):
        verify_sha256(b"payload", "0" * 64)


def test_safe_extract_tar_rejects_path_traversal(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        info = tarfile.TarInfo(name="../escape.txt")
        info.size = 4
        archive.addfile(info, io.BytesIO(b"evil"))
    with pytest.raises(Exception, match="Unsafe archive path"):
        safe_extract_tar(payload.getvalue(), tmp_path / "dest")


def test_deploy_plugin_copies_bundle(tmp_path: Path) -> None:
    package = tmp_path / "package"
    source = package / "plugin/model-providers/cursor"
    source.mkdir(parents=True)
    (source / "plugin.yaml").write_text("kind: model-provider\n", encoding="utf-8")
    home = tmp_path / "home"
    destination = deploy_plugin(package, home)
    assert destination.is_dir()
    assert (destination / "plugin.yaml").is_file()


def test_execute_install_plan_plugin_mode(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = tmp_path / "hermes-agent"
    source.mkdir()
    hermes = source / "venv/bin/hermes"
    hermes.parent.mkdir(parents=True)
    hermes.write_bytes(b"hermes")
    hermes.chmod(0o755)

    package = tmp_path / "package"
    plugin = package / "plugin/model-providers/cursor"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text("kind: model-provider\n", encoding="utf-8")
    (plugin / "__init__.py").write_text(
        "from providers import register_provider\n", encoding="utf-8"
    )

    bridge_name = "cursor-sdk-bridge"
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        data = b"#!/bin/sh\necho bridge\n"
        info = tarfile.TarInfo(name=f"bin/{bridge_name}")
        info.size = len(data)
        info.mode = 0o755
        tar.addfile(info, io.BytesIO(data))
    digest = hashlib.sha256(archive.getvalue()).hexdigest()

    runtime = Runtime(
        "posix-current",
        ("cli",),
        "linux",
        home,
        source,
        hermes,
        "0.21.1",
        True,
        "active",
    )
    manifest = InstallManifest(
        version="0.2.0a1",
        artifacts={
            "linux-x64": {
                "filename": "bridge.tar.gz",
                "sha256": digest,
                "url": "https://example.invalid/bridge.tar.gz",
            }
        },
    )
    capabilities = CapabilityReport(
        runtime_id="posix-current",
        hermes_version="0.21.1",
        source_root=source,
        plugin_seam=True,
        provider_client_seam=True,
        plugin_registered=True,
        client_contract=True,
    )
    plan = build_install_plan(
        runtime=runtime,
        manifest=manifest,
        profile="default",
        architecture="x64",
        capability_report=capabilities,
    )

    calls: list[list[str]] = []

    def run(args: list[str], cwd: Path, interactive: bool = False) -> CommandResult:
        calls.append(args)
        if args[-2:] == ["config", "path"]:
            config = home / "config.yaml"
            config.parent.mkdir(parents=True, exist_ok=True)
            return CommandResult(0, str(config), "")
        if args[1:4] == ["config", "set", "model.provider"]:
            raise AssertionError("additive install must not switch default model")
        if args[-3:] == ["auth", "status", "cursor"]:
            return CommandResult(0, "cursor: logged out\n", "")
        if args[1:] == ["--version"]:
            return CommandResult(0, "Hermes Agent v0.21.1\n", "")
        return CommandResult(0, "", "")

    def fake_receipt(runtime, *, bridge_path, notes=()):
        return InstallReceipt(
            host="test",
            runtime_id=runtime.runtime_id,
            hermes_version=runtime.version,
            hermes_home=str(runtime.home),
            plugin_path=str(runtime.home / "plugins/model-providers/cursor"),
            plugin_installed=True,
            bridge_path=str(bridge_path),
            bridge_installed=True,
            auth_status="logged out",
            auth_source="",
            model_catalog_count=None,
            model_catalog_error="",
            chat_probe="skipped_logged_out",
            contract_checks={
                "plugin_seam": True,
                "provider_client_seam": True,
                "plugin_registered": True,
                "client_contract": True,
            },
            notes=notes,
        )

    import hermes_cursor_native.installer as installer_mod

    original = installer_mod.collect_receipt
    installer_mod.collect_receipt = fake_receipt
    try:
        result = execute_install_plan(
            plan,
            package_root=package,
            approved=True,
            run=run,
            download=lambda _url: archive.getvalue(),
            executable_probe=lambda _runtime: ("0.21.1", source),
        )
    finally:
        installer_mod.collect_receipt = original

    assert result.bridge_path.is_file()
    assert result.plugin_path.is_dir()
