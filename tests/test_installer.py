from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

import pytest

from hermes_cursor_native.discovery import Runtime
from hermes_cursor_native.install_plan import (
    GitState,
    InstallManifest,
    build_install_plan,
)
from hermes_cursor_native.installer import (
    ApprovalRequiredError,
    ChecksumMismatchError,
    CommandResult,
    InstallerError,
    UnsafeArchiveError,
    UnsupportedRuntimeApplyError,
    execute_install_plan,
    require_approval,
    safe_extract_tar,
    validate_smoke_output,
    verify_sha256,
)
from hermes_cursor_native.preflight import probe_git_state


def test_apply_requires_explicit_approval() -> None:
    with pytest.raises(ApprovalRequiredError):
        require_approval(False)

    require_approval(True)


def test_verify_sha256_accepts_expected_digest() -> None:
    payload = b"verified bridge archive"

    verify_sha256(
        payload,
        "a75acc00784d9ae9151a686583b7295328df44c696743a01508e8612f9b18faa",
    )


def test_verify_sha256_rejects_mismatch() -> None:
    with pytest.raises(ChecksumMismatchError):
        verify_sha256(b"tampered", "0" * 64)


def test_smoke_output_requires_expected_marker() -> None:
    with pytest.raises(InstallerError, match="Composer smoke"):
        validate_smoke_output(
            CommandResult(0, "wrong response", ""),
            "COMPOSER_OK",
            "Composer",
        )

    validate_smoke_output(
        CommandResult(0, "COMPOSER_OK\n", ""),
        "COMPOSER_OK",
        "Composer",
    )


def _archive(name: str, content: bytes = b"x") -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


def test_safe_extract_tar_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(UnsafeArchiveError):
        safe_extract_tar(_archive("../escape.txt"), tmp_path)

    assert not (tmp_path.parent / "escape.txt").exists()


def test_safe_extract_tar_extracts_contained_file(tmp_path: Path) -> None:
    safe_extract_tar(_archive("bridge/bin/cursor-sdk-bridge", b"binary"), tmp_path)

    assert (tmp_path / "bridge/bin/cursor-sdk-bridge").read_bytes() == b"binary"


def test_execute_install_plan_runs_ordered_secret_free_commands(tmp_path: Path) -> None:
    source = tmp_path / "hermes-agent"
    source.mkdir()
    executable = source / "venv/Scripts/hermes.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"launcher")
    config_path = tmp_path / "hermes-home/config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("model: old\n", encoding="utf-8")
    runtime = Runtime(
        "windows-current",
        ("cli",),
        "windows",
        tmp_path / "hermes-home",
        source,
        executable,
        "0.20.5",
        True,
        "active",
    )
    patch_root = tmp_path / "package" / "patches/hermes/0.20.5"
    patch_root.mkdir(parents=True)
    (patch_root / "0001.patch").write_text("patch", encoding="utf-8")
    archive = _archive("bridge/bin/cursor-sdk-bridge.exe", b"binary")
    import hashlib

    manifest = InstallManifest(
        version="0.1.0a1",
        supported_hermes=("0.20.5",),
        base_commits=("base",),
        artifacts={
            "windows-x64": {
                "filename": "bridge.tar.gz",
                "sha256": hashlib.sha256(archive).hexdigest(),
                "url": "https://example.invalid/bridge.tar.gz",
            }
        },
        patch_series=("0001.patch",),
    )
    plan = build_install_plan(
        runtime=runtime,
        manifest=manifest,
        profile="default",
        git_state=GitState(clean=True, branch="main", head="base"),
        architecture="x64",
    )
    calls: list[tuple[list[str], Path, bool]] = []
    patched = [False]

    def run(args: list[str], cwd: Path, interactive: bool = False) -> CommandResult:
        calls.append((args, cwd, interactive))
        if args[1:3] == ["show-ref", "--verify"]:
            return CommandResult(1, "", "")
        if args[-2:] == ["config", "path"]:
            return CommandResult(0, str(config_path), "")
        if args[1:2] == ["am"]:
            patched[0] = True
        if "chat" in args:
            query = args[args.index("-q") + 1]
            if "COMPOSER_OK" in query:
                return CommandResult(0, "COMPOSER_OK\n", "")
            if "GROK_OK" in query:
                return CommandResult(0, "GROK_OK\n", "")
            if "AUTO_OK" in query:
                return CommandResult(0, "AUTO_OK\n", "")
            if "tool-smoke.txt" in query:
                return CommandResult(0, "TOOL_NONCE\n", "")
        return CommandResult(0, "", "")

    result = execute_install_plan(
        plan,
        package_root=tmp_path / "package",
        approved=True,
        run=run,
        download=lambda _url: archive,
        timestamp=lambda: "20260822-010000",
        provider_validator=lambda _root, _hashes: patched[0],
        git_probe=lambda _root: GitState(
            clean=True, branch=plan.original_branch, head=plan.original_head
        ),
        executable_probe=lambda _runtime: (runtime.version, source),
        nonce_factory=lambda: "TOOL_NONCE",
    )

    flattened = "\n".join(" ".join(args) for args, _cwd, _interactive in calls)
    assert "CURSOR_API_KEY" not in flattened
    assert "auth.json" not in flattened
    assert "git branch backup/hermes-cursor-native-20260822-010000" in flattened
    assert "git switch -c cursor-provider-deployed" in flattened
    assert "git am" in flattened
    assert "cursor login" in flattened
    assert calls[-1][2] is False
    assert result.bridge_path.name == "cursor-sdk-bridge.exe"
    assert result.config_backup is not None
    assert result.config_backup.read_text(encoding="utf-8") == "model: old\n"
    assert result.branch == "cursor-provider-deployed"


def test_windows_executor_refuses_cross_os_wsl_mutation(tmp_path: Path) -> None:
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
    manifest = InstallManifest(
        version="0.1.0a1",
        supported_hermes=("0.20.5",),
        base_commits=("base",),
        artifacts={
            "linux-x64": {
                "filename": "bridge.tar.gz",
                "sha256": "a" * 64,
                "url": "https://example.invalid/bridge.tar.gz",
            }
        },
        patch_series=("0001.patch",),
    )
    plan = build_install_plan(
        runtime=runtime,
        manifest=manifest,
        profile="default",
        git_state=GitState(clean=True, branch="main", head="base"),
        architecture="x64",
    )

    with pytest.raises(UnsupportedRuntimeApplyError, match="inside WSL"):
        execute_install_plan(
            plan,
            package_root=tmp_path,
            approved=True,
            host_os="nt",
        )


def test_executor_refuses_divergent_existing_deployment_branch(tmp_path: Path) -> None:
    source = tmp_path / "hermes-agent"
    source.mkdir()
    executable = source / "venv/Scripts/hermes.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"launcher")
    runtime = Runtime(
        "windows-current",
        ("cli",),
        "windows",
        tmp_path / "home",
        source,
        executable,
        "0.20.5",
        True,
        "active",
    )
    manifest = InstallManifest(
        version="0.1.0a1",
        supported_hermes=("0.20.5",),
        base_commits=("current",),
        artifacts={
            "windows-x64": {
                "filename": "bridge.tar.gz",
                "sha256": "a" * 64,
                "url": "https://example.invalid/bridge.tar.gz",
            }
        },
        patch_series=("0001.patch",),
    )
    plan = build_install_plan(
        runtime=runtime,
        manifest=manifest,
        profile="default",
        git_state=GitState(clean=True, branch="main", head="current"),
        architecture="x64",
    )
    calls = []

    def run(args: list[str], cwd: Path, interactive: bool = False) -> CommandResult:
        calls.append(args)
        if args[1:3] == ["show-ref", "--verify"]:
            return CommandResult(0, "", "")
        if args[1:] == ["rev-parse", "HEAD"]:
            return CommandResult(0, "current\n", "")
        if args[1:] == ["rev-parse", "cursor-provider-deployed"]:
            return CommandResult(0, "stale\n", "")
        return CommandResult(0, "", "")

    with pytest.raises(InstallerError, match="diverges"):
        execute_install_plan(
            plan,
            package_root=tmp_path,
            approved=True,
            run=run,
            timestamp=lambda: "20260822-010000",
            git_probe=lambda _root: GitState(
                clean=True, branch=plan.original_branch, head=plan.original_head
            ),
            executable_probe=lambda _runtime: (runtime.version, source),
        )

    assert ["git", "switch", "cursor-provider-deployed"] not in calls
    assert not any(call[1:2] == ["branch"] for call in calls)


def test_executor_revalidates_git_state_before_any_mutation(tmp_path: Path) -> None:
    source = tmp_path / "hermes-agent"
    source.mkdir()
    executable = source / "venv/Scripts/hermes.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"launcher")
    runtime = Runtime(
        "windows-current",
        ("cli",),
        "windows",
        tmp_path / "home",
        source,
        executable,
        "0.20.5",
        True,
        "active",
    )
    manifest = InstallManifest(
        version="0.1.0a1",
        supported_hermes=("0.20.5",),
        base_commits=("approved-head",),
        artifacts={
            "windows-x64": {
                "filename": "bridge.tar.gz",
                "sha256": "a" * 64,
                "url": "https://example.invalid/bridge.tar.gz",
            }
        },
        patch_series=(),
    )
    plan = build_install_plan(
        runtime=runtime,
        manifest=manifest,
        profile="default",
        git_state=GitState(clean=True, branch="main", head="approved-head"),
        architecture="x64",
    )
    calls = []

    with pytest.raises(InstallerError, match="changed after approval"):
        execute_install_plan(
            plan,
            package_root=tmp_path,
            approved=True,
            run=lambda args, _cwd, _interactive=False: calls.append(args),
            git_probe=lambda _root: GitState(
                clean=False,
                branch="main",
                head="different-head",
            ),
            executable_probe=lambda _runtime: (runtime.version, source),
        )

    assert calls == []

    executable.write_bytes(b"replaced executable")
    with pytest.raises(InstallerError, match="executable changed after approval"):
        execute_install_plan(
            plan,
            package_root=tmp_path,
            approved=True,
            run=lambda args, _cwd, _interactive=False: calls.append(args),
            git_probe=lambda _root: GitState(
                clean=True,
                branch=plan.original_branch,
                head=plan.original_head,
            ),
            executable_probe=lambda _runtime: (runtime.version, source),
        )

    assert calls == []


def test_branch_creation_interrupt_restores_original_branch(tmp_path: Path) -> None:
    source = tmp_path / "hermes-agent"
    source.mkdir()
    executable = source / "venv/Scripts/hermes.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"launcher")
    runtime = Runtime(
        "windows-current",
        ("cli",),
        "windows",
        tmp_path / "home",
        source,
        executable,
        "0.20.5",
        True,
        "active",
    )
    manifest = InstallManifest(
        version="0.1.0a1",
        supported_hermes=("0.20.5",),
        base_commits=("base",),
        artifacts={
            "windows-x64": {
                "filename": "bridge.tar.gz",
                "sha256": "a" * 64,
                "url": "https://example.invalid/bridge.tar.gz",
            }
        },
        patch_series=("0001.patch",),
    )
    plan = build_install_plan(
        runtime=runtime,
        manifest=manifest,
        profile="default",
        git_state=GitState(clean=True, branch="main", head="base"),
        architecture="x64",
    )
    calls = []

    def run(args: list[str], cwd: Path, interactive: bool = False) -> CommandResult:
        calls.append(args)
        if args[1:3] == ["show-ref", "--verify"]:
            return CommandResult(1, "", "")
        if args[1:4] == ["switch", "-c", "cursor-provider-deployed"]:
            raise KeyboardInterrupt
        return CommandResult(0, "", "")

    with pytest.raises(KeyboardInterrupt):
        execute_install_plan(
            plan,
            package_root=tmp_path,
            approved=True,
            run=run,
            timestamp=lambda: "20260822-010000",
            git_probe=lambda _root: GitState(
                clean=True, branch=plan.original_branch, head=plan.original_head
            ),
            executable_probe=lambda _runtime: (runtime.version, source),
        )

    assert ["git", "branch", "backup/hermes-cursor-native-20260822-010000", "HEAD"] in calls
    assert ["git", "switch", "main"] in calls


def test_executor_restores_config_and_previous_bridge_on_keyboard_interrupt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "hermes-agent"
    source.mkdir()
    executable = source / "venv/Scripts/hermes.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"launcher")
    home = tmp_path / "home"
    config_path = home / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("model: old\n", encoding="utf-8")
    old_bridge_root = home / "cursor-native/bridge/0.1.0a1"
    old_bridge_root.mkdir(parents=True)
    (old_bridge_root / "old.txt").write_text("old bridge", encoding="utf-8")
    runtime = Runtime(
        "windows-current",
        ("cli",),
        "windows",
        home,
        source,
        executable,
        "0.20.5",
        True,
        "active",
    )
    archive = _archive("bridge/bin/cursor-sdk-bridge.exe", b"new bridge")
    import hashlib

    manifest = InstallManifest(
        version="0.1.0a1",
        supported_hermes=("0.20.5",),
        base_commits=("base",),
        artifacts={
            "windows-x64": {
                "filename": "bridge.tar.gz",
                "sha256": hashlib.sha256(archive).hexdigest(),
                "url": "https://example.invalid/bridge.tar.gz",
            }
        },
        patch_series=("0001.patch",),
    )
    patch_root = tmp_path / "package/patches/hermes/0.20.5"
    patch_root.mkdir(parents=True)
    (patch_root / "0001.patch").write_text("patch", encoding="utf-8")
    plan = build_install_plan(
        runtime=runtime,
        manifest=manifest,
        profile="default",
        git_state=GitState(clean=True, branch="main", head="base"),
        architecture="x64",
    )
    calls = []
    patched = [False]

    def run(args: list[str], cwd: Path, interactive: bool = False) -> CommandResult:
        calls.append(args)
        if args[1:3] == ["show-ref", "--verify"]:
            return CommandResult(1, "", "")
        if args[-2:] == ["config", "path"]:
            return CommandResult(0, str(config_path), "")
        if args[1:3] == ["config", "set"]:
            raise KeyboardInterrupt
        if args[1:2] == ["am"]:
            patched[0] = True
        return CommandResult(0, "", "")

    with pytest.raises(KeyboardInterrupt):
        execute_install_plan(
            plan,
            package_root=tmp_path / "package",
            approved=True,
            run=run,
            download=lambda _url: archive,
            timestamp=lambda: "20260822-010000",
            provider_validator=lambda _root, _hashes: patched[0],
            git_probe=lambda _root: GitState(
                clean=True, branch=plan.original_branch, head=plan.original_head
            ),
            executable_probe=lambda _runtime: (runtime.version, source),
        )

    assert config_path.read_text(encoding="utf-8") == "model: old\n"
    assert (old_bridge_root / "old.txt").read_text(encoding="utf-8") == "old bridge"
    assert ["git", "am", "--abort"] not in calls
    assert ["git", "switch", "main"] in calls


def test_executor_removes_new_config_and_bridge_on_keyboard_interrupt(tmp_path: Path) -> None:
    source = tmp_path / "hermes-agent"
    source.mkdir()
    executable = source / "venv/Scripts/hermes.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"launcher")
    home = tmp_path / "home"
    config_path = home / "config.yaml"
    runtime = Runtime(
        "windows-current",
        ("cli",),
        "windows",
        home,
        source,
        executable,
        "0.20.5",
        True,
        "active",
    )
    archive = _archive("bridge/bin/cursor-sdk-bridge.exe", b"new bridge")
    import hashlib

    manifest = InstallManifest(
        version="0.1.0a1",
        supported_hermes=("0.20.5",),
        base_commits=("base",),
        artifacts={
            "windows-x64": {
                "filename": "bridge.tar.gz",
                "sha256": hashlib.sha256(archive).hexdigest(),
                "url": "https://example.invalid/bridge.tar.gz",
            }
        },
        patch_series=("0001.patch",),
    )
    patch_root = tmp_path / "package/patches/hermes/0.20.5"
    patch_root.mkdir(parents=True)
    (patch_root / "0001.patch").write_text("patch", encoding="utf-8")
    plan = build_install_plan(
        runtime=runtime,
        manifest=manifest,
        profile="default",
        git_state=GitState(clean=True, branch="main", head="base"),
        architecture="x64",
    )
    calls = []
    patched = [False]

    def run(args: list[str], cwd: Path, interactive: bool = False) -> CommandResult:
        calls.append(args)
        if args[1:3] == ["show-ref", "--verify"]:
            return CommandResult(1, "", "")
        if args[-2:] == ["config", "path"]:
            return CommandResult(0, str(config_path), "")
        if args[1:2] == ["am"]:
            patched[0] = True
        if args[1:3] == ["config", "set"]:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("created-by-install\n", encoding="utf-8")
        if args[1:3] == ["cursor", "login"]:
            raise KeyboardInterrupt
        return CommandResult(0, "", "")

    with pytest.raises(KeyboardInterrupt):
        execute_install_plan(
            plan,
            package_root=tmp_path / "package",
            approved=True,
            run=run,
            download=lambda _url: archive,
            timestamp=lambda: "20260822-010000",
            provider_validator=lambda _root, _hashes: patched[0],
            git_probe=lambda _root: GitState(
                clean=True, branch=plan.original_branch, head=plan.original_head
            ),
            executable_probe=lambda _runtime: (runtime.version, source),
        )

    assert not config_path.exists()
    assert not (home / "cursor-native/bridge/0.1.0a1").exists()


@pytest.mark.parametrize("detached", [False, True])
def test_real_git_fresh_branch_failure_restores_inventory(
    tmp_path: Path, detached: bool
) -> None:
    source = tmp_path / "hermes-agent"
    source.mkdir()

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(source), *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Hermes Cursor Native Test")
    git("config", "user.email", "test@example.invalid")
    executable = source / "venv/Scripts/hermes.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"launcher")
    git("add", ".")
    git("commit", "-m", "base")
    head = git("rev-parse", "HEAD")
    if detached:
        git("checkout", "--detach", head)
    approved_git = probe_git_state(source)

    runtime = Runtime(
        "windows-current",
        ("cli",),
        "windows",
        tmp_path / "home",
        source,
        executable,
        "0.20.5",
        True,
        "active",
    )
    manifest = InstallManifest(
        version="0.1.0a1",
        supported_hermes=("0.20.5",),
        base_commits=(head,),
        artifacts={
            "windows-x64": {
                "filename": "bridge.tar.gz",
                "sha256": "a" * 64,
                "url": "https://example.invalid/bridge.tar.gz",
            }
        },
        patch_series=(),
    )
    plan = build_install_plan(
        runtime=runtime,
        manifest=manifest,
        profile="default",
        git_state=approved_git,
        architecture="x64",
    )

    with pytest.raises(KeyboardInterrupt):
        execute_install_plan(
            plan,
            package_root=tmp_path,
            approved=True,
            download=lambda _url: (_ for _ in ()).throw(KeyboardInterrupt()),
            timestamp=lambda: "20260822-010000",
            provider_validator=lambda _root, _hashes: True,
            executable_probe=lambda _runtime: (runtime.version, source),
        )

    assert git("branch", "--show-current") == ("" if detached else "main")
    assert git("rev-parse", "HEAD") == head
    branches = set(git("branch", "--format=%(refname:short)").splitlines())
    assert "cursor-provider-deployed" not in branches
    assert "backup/hermes-cursor-native-20260822-010000" in branches


def test_existing_deployment_branch_ref_is_restored_after_failure(tmp_path: Path) -> None:
    source = tmp_path / "hermes-agent"
    source.mkdir()
    executable = source / "venv/Scripts/hermes.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"launcher")
    runtime = Runtime(
        "windows-current",
        ("cli",),
        "windows",
        tmp_path / "home",
        source,
        executable,
        "0.20.5",
        True,
        "active",
    )
    manifest = InstallManifest(
        version="0.1.0a1",
        supported_hermes=("0.20.5",),
        base_commits=("base",),
        artifacts={
            "windows-x64": {
                "filename": "bridge.tar.gz",
                "sha256": "a" * 64,
                "url": "https://example.invalid/bridge.tar.gz",
            }
        },
        patch_series=("0001.patch",),
    )
    patch_root = tmp_path / "patches/hermes/0.20.5"
    patch_root.mkdir(parents=True)
    (patch_root / "0001.patch").write_text("patch", encoding="utf-8")
    plan = build_install_plan(
        runtime=runtime,
        manifest=manifest,
        profile="default",
        git_state=GitState(clean=True, branch="main", head="base"),
        architecture="x64",
    )
    calls = []
    patched = [False]

    def run(args: list[str], cwd: Path, interactive: bool = False) -> CommandResult:
        calls.append(args)
        if args[1:3] == ["show-ref", "--verify"]:
            return CommandResult(0, "", "")
        if args[1:] == ["rev-parse", "HEAD"]:
            return CommandResult(0, "base\n", "")
        if args[1:] == ["rev-parse", "cursor-provider-deployed"]:
            return CommandResult(0, "base\n", "")
        if args[1:2] == ["am"]:
            patched[0] = True
        return CommandResult(0, "", "")

    with pytest.raises(KeyboardInterrupt):
        execute_install_plan(
            plan,
            package_root=tmp_path,
            approved=True,
            run=run,
            download=lambda _url: (_ for _ in ()).throw(KeyboardInterrupt()),
            provider_validator=lambda _root, _hashes: patched[0],
            git_probe=lambda _root: GitState(clean=True, branch="main", head="base"),
            executable_probe=lambda _runtime: (runtime.version, source),
        )

    assert ["git", "switch", "main"] in calls
    assert ["git", "branch", "-f", "cursor-provider-deployed", "base"] in calls
