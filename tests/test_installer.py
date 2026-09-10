from __future__ import annotations

import hashlib
import io
import os
import tarfile
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from hermes_cursor_native.capabilities import CapabilityReport
from hermes_cursor_native.discovery import Runtime
from hermes_cursor_native.install_plan import InstallPlan, build_install_plan
from hermes_cursor_native.installer import (
    ApprovalRequiredError,
    CommandResult,
    InstallerError,
    deploy_plugin,
    execute_install_plan,
    require_approval,
    run_command,
    run_cursor_oauth,
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


@pytest.mark.parametrize("profile", ["default", "work"])
@pytest.mark.parametrize("native_runner", [False, True])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", [None, "copy", "checksum", "config", "contract"])
def test_execute_install_plan_plugin_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool, failure: str | None,
    native_runner: bool, profile: str,
) -> None:
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
        profile=profile,
        profile_exists=True,
        architecture="x64",
        capability_report=capabilities,
    )

    plugin_home = home if profile == "default" else home / "profiles" / profile
    destination = plugin_home / "plugins/model-providers/cursor"
    bridge_root = home / "cursor-sdk-bridge"
    config = home / "config.yaml"
    if existing:
        destination.mkdir(parents=True)
        (destination / "old.py").write_bytes(b"previous plugin")
        bridge_root.mkdir()
        (bridge_root / "old-bridge").write_bytes(b"previous bridge")
        config.write_bytes(b"previous config")

    calls: list[list[str]] = []

    def run(args: list[str], cwd: Path, interactive: bool = False) -> CommandResult:
        calls.append(args)
        args = [args[0], *args[3:]] if args[1:3] == ["-p", profile] else args
        if args[-2:] == ["config", "path"]:
            config.parent.mkdir(parents=True, exist_ok=True)
            return CommandResult(0, str(config), "")
        if args[1:3] == ["config", "set"]:
            config.write_bytes(b"new config")
            if failure == "config":
                return CommandResult(1, "", "injected config failure")
        if args[1:4] == ["config", "set", "model.provider"]:
            raise AssertionError("additive install must not switch default model")
        if args[-3:] == ["auth", "status", "cursor"]:
            return CommandResult(0, "cursor: logged out\n", "")
        if args[1:] == ["--version"]:
            return CommandResult(0, "Hermes Agent v0.21.1\n", "")
        return CommandResult(0, "", "")

    def fake_receipt(runtime, *, bridge_path, notes=(), profile="default"):
        assert profile == plan.profile
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
                "client_contract": failure != "contract",
            },
            notes=notes,
        )

    import hermes_cursor_native.installer as installer_mod

    monkeypatch.setattr(installer_mod, "collect_receipt", fake_receipt)
    if failure == "copy":
        def failing_copy(source, target):
            Path(target).mkdir(parents=True)
            (Path(target) / "partial.py").write_bytes(b"incomplete")
            raise OSError("injected copy failure")

        monkeypatch.setattr(installer_mod.shutil, "copytree", failing_copy)

    if failure == "bridge_backup":
        original_mkdtemp = installer_mod.tempfile.mkdtemp

        def fail_bridge_backup(*args, **kwargs):
            if kwargs.get("prefix") == "bridge-":
                raise OSError("injected bridge backup failure")
            return original_mkdtemp(*args, **kwargs)

        monkeypatch.setattr(installer_mod.tempfile, "mkdtemp", fail_bridge_backup)
    if failure == "bridge_move":
        original_rename = Path.rename

        def fail_bridge_move(path, target):
            if path == bridge_root:
                raise OSError("injected bridge move failure")
            return original_rename(path, target)

        monkeypatch.setattr(Path, "rename", fail_bridge_move)

    def subprocess_run(args, *, cwd, env, **kwargs):
        assert env["HERMES_HOME"] == str(home)
        result = run(args, cwd)
        return CompletedProcess(args, result.returncode, result.stdout, result.stderr)

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "unrelated-home"))
    if native_runner:
        monkeypatch.setattr(installer_mod.subprocess, "run", subprocess_run)

    def install():
        return execute_install_plan(
            plan,
            package_root=package,
            approved=True,
            run=None if native_runner else run,
            download=lambda _url: b"corrupted" if failure == "checksum" else archive.getvalue(),
            executable_probe=lambda _runtime: ("0.21.1", source),
        )

    if failure:
        expected = {
            "bridge_backup": "injected bridge backup failure",
            "bridge_move": "injected bridge move failure",
            "copy": "injected copy failure",
            "checksum": "SHA256 mismatch",
            "config": "injected config failure",
            "contract": "client contract checks failed",
        }
        with pytest.raises((InstallerError, OSError), match=expected[failure]):
            install()
        if existing:
            assert {p.name: p.read_bytes() for p in destination.iterdir()} == {
                "old.py": b"previous plugin",
            }
            assert (bridge_root / "old-bridge").read_bytes() == b"previous bridge"
            assert config.read_bytes() == b"previous config"
        else:
            assert not destination.exists()
            assert not bridge_root.exists()
            assert not config.exists()
    else:
        result = install()
        assert result.bridge_path.is_file()
        assert (result.plugin_path / "plugin.yaml").is_file()
        assert not (result.plugin_path / "old.py").exists()


@pytest.mark.parametrize("failure", ["bridge_backup", "bridge_move"])
def test_bridge_backup_failure_preserves_existing_install(tmp_path, monkeypatch, failure):
    test_execute_install_plan_plugin_mode(
        tmp_path, monkeypatch, existing=True, failure=failure,
        native_runner=False, profile="default",
    )


def test_execute_install_plan_wraps_executable_probe_failures(tmp_path):
    home = tmp_path / "home"
    source = tmp_path / "source"
    source.mkdir()
    hermes = source / "venv/bin/hermes"
    hermes.parent.mkdir(parents=True)
    hermes.write_bytes(b"hermes")
    hermes.chmod(0o755)
    package = tmp_path / "package"
    runtime = Runtime(
        "posix-current", ("cli",), "linux", home, source, hermes, "0.21.1", True, "active",
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
    plan = InstallPlan(
        runtime=runtime,
        profile="default",
        manifest_version="0.2.0a1",
        artifact_key="linux-x64",
        artifact={"url": "https://example.invalid/bridge.tar.gz", "sha256": "0" * 64},
        executable_sha256=hashlib.sha256(b"hermes").hexdigest(),
        operations=(),
        capabilities=capabilities,
    )

    import subprocess

    def timeout_probe(_runtime):
        raise subprocess.TimeoutExpired("cmd", 30)

    with pytest.raises(InstallerError, match="identity could not be verified"):
        execute_install_plan(
            plan,
            package_root=package,
            approved=True,
            run=lambda *_args: CommandResult(0, "", ""),
            download=lambda _url: b"",
            executable_probe=timeout_probe,
        )


def test_execute_install_plan_rejects_changed_runtime_source(tmp_path):
    home = tmp_path / "home"
    approved = tmp_path / "approved"
    changed = tmp_path / "changed"
    approved.mkdir()
    changed.mkdir()
    hermes = approved / "venv/bin/hermes"
    hermes.parent.mkdir(parents=True)
    hermes.write_bytes(b"hermes")
    hermes.chmod(0o755)

    package = tmp_path / "package"
    runtime = Runtime(
        "posix-current", ("cli",), "linux", home, approved, hermes, "0.21.1", True, "active",
    )
    capabilities = CapabilityReport(
        runtime_id="posix-current",
        hermes_version="0.21.1",
        source_root=approved,
        plugin_seam=True,
        provider_client_seam=True,
        plugin_registered=True,
        client_contract=True,
    )
    plan = InstallPlan(
        runtime=runtime,
        profile="default",
        manifest_version="0.2.0a1",
        artifact_key="linux-x64",
        artifact={"url": "https://example.invalid/bridge.tar.gz", "sha256": "0" * 64},
        executable_sha256=hashlib.sha256(b"hermes").hexdigest(),
        operations=(),
        capabilities=capabilities,
    )

    def run(_args, _cwd, _interactive=False):
        return CommandResult(0, "", "")

    with pytest.raises(InstallerError, match="runtime source changed"):
        execute_install_plan(
            plan,
            package_root=package,
            approved=True,
            run=run,
            download=lambda _url: b"",
            executable_probe=lambda _runtime: ("0.21.1", changed),
        )


def test_run_cursor_oauth_surfaces_genuine_login_failure(tmp_path):
    hermes = tmp_path / "hermes"
    source = tmp_path / "source"
    source.mkdir()
    home = tmp_path / "home"
    package = tmp_path / "package"

    def run(args, _cwd, interactive=False):
        if args[-1] == "--help":
            return CommandResult(0, "", "")
        if args[-2:] == ["cursor", "login"] and interactive:
            return CommandResult(1, "", "login timed out")
        pytest.fail(f"unexpected invocation: {args!r} interactive={interactive}")

    with pytest.raises(InstallerError, match="Cursor OAuth failed: login timed out"):
        run_cursor_oauth(run, hermes, source, home, package)


def test_run_cursor_oauth_prefers_login_failure_over_help_probe(tmp_path):
    hermes = tmp_path / "hermes"
    source = tmp_path / "source"
    source.mkdir()
    home = tmp_path / "home"
    package = tmp_path / "package"

    def run(args, _cwd, interactive=False):
        if args[-1] == "--help":
            return CommandResult(0, "Usage: hermes cursor login [options]", "")
        if args[-2:] == ["cursor", "login"] and interactive:
            return CommandResult(1, "", "login cancelled")
        pytest.fail(f"unexpected invocation: {args!r} interactive={interactive}")

    with pytest.raises(InstallerError, match="Cursor OAuth failed: login cancelled"):
        run_cursor_oauth(run, hermes, source, home, package)


def test_run_cursor_oauth_runs_supported_login_once(tmp_path):
    hermes = tmp_path / "hermes"
    source = tmp_path / "source"
    source.mkdir()
    home = tmp_path / "home"
    package = tmp_path / "package"
    calls: list[tuple[list[str], bool]] = []

    def run(args, _cwd, interactive=False):
        calls.append((list(args), interactive))
        if args[-1] == "--help":
            return CommandResult(0, "", "")
        if args[-2:] == ["cursor", "login"]:
            return CommandResult(0, "", "")
        return CommandResult(0, "", "")

    run_cursor_oauth(run, hermes, source, home, package)
    login_calls = [call for call in calls if call[0][-2:] == ["cursor", "login"]]
    assert len(login_calls) == 1
    assert login_calls[0][1] is True
    assert login_calls[0][0][0] == str(hermes)


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell stub is not executable on Windows")
def test_run_cursor_oauth_probes_before_interactive_login(tmp_path, monkeypatch):
    hermes = tmp_path / "hermes"
    hermes.write_text(
        "#!/bin/sh\n"
        "if [ \"$3\" = \"--help\" ]; then\n"
        "  echo \"Error: No such command 'cursor'.\" >&2\n"
        "  exit 2\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    hermes.chmod(0o755)
    source = tmp_path / "source"
    source.mkdir()
    home = tmp_path / "home"
    package = tmp_path / "package"
    auth_script = package / "plugin/model-providers/cursor/cursor_sdk_auth.py"
    auth_script.parent.mkdir(parents=True)
    auth_script.write_text("#!/usr/bin/env python3\nimport sys; sys.exit(0)\n", encoding="utf-8")
    auth_script.chmod(0o755)

    import hermes_cursor_native.installer as installer_mod

    monkeypatch.setattr(installer_mod.sys, "executable", "/usr/bin/python3")
    run_cursor_oauth(run_command, hermes, source, home, package)


def test_run_cursor_oauth_falls_back_when_command_missing(tmp_path, monkeypatch):
    hermes = tmp_path / "hermes"
    source = tmp_path / "source"
    source.mkdir()
    home = tmp_path / "home"
    package = tmp_path / "package"
    auth_script = package / "plugin/model-providers/cursor/cursor_sdk_auth.py"
    auth_script.parent.mkdir(parents=True)
    auth_script.write_text("print('ok')\n", encoding="utf-8")
    calls: list[list[str]] = []

    def run(args, _cwd, interactive=False):
        calls.append((args, interactive))
        if args[-3:] == ["cursor", "login", "--help"]:
            return CommandResult(2, "", "Error: No such command 'cursor'.")
        return CommandResult(0, "", "")

    import hermes_cursor_native.installer as installer_mod

    monkeypatch.setattr(installer_mod.sys, "executable", "/usr/bin/python3")
    run_cursor_oauth(run, hermes, source, home, package)
    assert len(calls) == 2
    assert calls[0][1] is False
    assert calls[1][0][0] == "/usr/bin/python3"
    assert calls[1][0][1].endswith("cursor_sdk_auth.py")
