"""Security-critical installer primitives for the Cursor model-provider plugin."""

from __future__ import annotations

import hashlib
import hmac
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path, PurePosixPath

from .discovery import Runtime
from .install_plan import InstallPlan
from .verify import InstallReceipt, collect_receipt


class InstallerError(RuntimeError):
    """Base installer failure."""


class ApprovalRequiredError(InstallerError):
    """Raised when a mutating install has not been explicitly approved."""


class ChecksumMismatchError(InstallerError):
    """Raised when a downloaded artifact fails integrity verification."""


class UnsafeArchiveError(InstallerError):
    """Raised when an archive contains unsafe paths or entry types."""


class UnsupportedRuntimeApplyError(InstallerError):
    """Raised when mutation must run inside another OS/runtime boundary."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class InstallResult:
    bridge_path: Path
    plugin_path: Path
    config_backup: Path | None
    receipt: InstallReceipt


CommandRunner = Callable[[list[str], Path, bool], CommandResult]
Downloader = Callable[[str], bytes]


def probe_executable_identity(runtime: Runtime) -> tuple[str, Path | None]:
    executable = Path(runtime.executable)  # type: ignore[arg-type]
    result = subprocess.run(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise InstallerError("Approved Hermes executable no longer runs successfully")
    from .system_discovery import parse_version_output

    return parse_version_output(f"{result.stdout}\n{result.stderr}")


def require_approval(approved: bool) -> None:
    if not approved:
        raise ApprovalRequiredError("Installation requires explicit approval")


def verify_sha256(payload: bytes, expected: str) -> None:
    actual = hashlib.sha256(payload).hexdigest()
    if not hmac.compare_digest(actual.casefold(), expected.casefold()):
        raise ChecksumMismatchError(f"SHA256 mismatch: expected {expected}, got {actual}")


def _safe_member_path(destination: Path, member_name: str) -> Path:
    logical = PurePosixPath(member_name)
    if logical.is_absolute() or ".." in logical.parts:
        raise UnsafeArchiveError(f"Unsafe archive path: {member_name!r}")
    target = destination.joinpath(*logical.parts)
    resolved_destination = destination.resolve(strict=False)
    resolved_target = target.resolve(strict=False)
    try:
        resolved_target.relative_to(resolved_destination)
    except ValueError as exc:
        raise UnsafeArchiveError(f"Archive path escapes destination: {member_name!r}") from exc
    return target


def _extract_archive(
    archive: tarfile.TarFile,
    destination: Path,
    *,
    max_files: int,
    max_total_bytes: int,
) -> None:
    members = archive.getmembers()
    if len(members) > max_files:
        raise UnsafeArchiveError(f"Archive has too many entries: {len(members)}")
    total_size = sum(member.size for member in members if member.isfile())
    if total_size > max_total_bytes:
        raise UnsafeArchiveError(f"Archive expands beyond {max_total_bytes} bytes")

    for member in members:
        target = _safe_member_path(destination, member.name)
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not member.isfile():
            raise UnsafeArchiveError(f"Archive entry type is not allowed: {member.name!r}")
        source = archive.extractfile(member)
        if source is None:
            raise UnsafeArchiveError(f"Could not read archive entry: {member.name!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with source, target.open("wb") as output:
            shutil.copyfileobj(source, output)


def safe_extract_tar(
    payload: bytes,
    destination: Path,
    *,
    max_files: int = 500,
    max_total_bytes: int = 512 * 1024 * 1024,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            _extract_archive(
                archive,
                destination,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
            )
    except tarfile.TarError as exc:
        raise UnsafeArchiveError(f"Invalid tar archive: {exc}") from exc


def run_command(
    args: list[str], cwd: Path, interactive: bool = False, *, env: dict[str, str] | None = None,
) -> CommandResult:
    if interactive:
        completed = subprocess.run(args, cwd=cwd, env=env, check=False)
        return CommandResult(completed.returncode, "", "")
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def download_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "hermes-cursor-native"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _checked(
    run: CommandRunner,
    args: list[str],
    cwd: Path,
    interactive: bool = False,
) -> CommandResult:
    result = run(args, cwd, interactive)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise InstallerError(f"Command failed: {' '.join(args)}: {detail}")
    return result


def _find_bridge(root: Path, platform: str) -> Path:
    expected = "cursor-sdk-bridge.exe" if platform == "windows" else "cursor-sdk-bridge"
    matches = [path for path in root.rglob(expected) if path.is_file()]
    if len(matches) != 1:
        raise InstallerError(f"Expected one {expected} in bridge archive, found {len(matches)}")
    bridge = matches[0]
    if platform != "windows":
        bridge.chmod(0o755)
    return bridge


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def run_cursor_oauth(
    run: CommandRunner,
    hermes: Path,
    source: Path,
    hermes_home: Path,
    package_root: Path,
) -> None:
    result = run([str(hermes), "cursor", "login"], source, True)
    if result.returncode == 0:
        return
    auth_script = hermes_home / "plugins" / "model-providers" / "cursor" / "cursor_sdk_auth.py"
    if not auth_script.is_file():
        auth_script = package_root / "plugin" / "model-providers" / "cursor" / "cursor_sdk_auth.py"
    if not auth_script.is_file():
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise InstallerError(
            "Cursor OAuth failed: `hermes cursor login` is unavailable and the plugin "
            f"auth script is missing ({detail})"
        )
    _checked(run, [sys.executable, str(auth_script)], source, True)


def deploy_plugin(package_root: Path, hermes_home: Path) -> Path:
    source = package_root / "plugin" / "model-providers" / "cursor"
    if not source.is_dir():
        raise InstallerError(f"Plugin source is missing: {source}")
    destination = hermes_home / "plugins" / "model-providers" / "cursor"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination


def execute_install_plan(
    plan: InstallPlan,
    *,
    package_root: Path,
    approved: bool,
    run: CommandRunner | None = None,
    download: Downloader = download_url,
    timestamp: Callable[[], str] = _timestamp,
    host_os: str = os.name,
    executable_probe: Callable[[Runtime], tuple[str, Path | None]] = probe_executable_identity,
) -> InstallResult:
    """Apply an approved plugin-only install plan."""

    require_approval(approved)
    if run is None:
        run = partial(run_command, env={**os.environ, "HERMES_HOME": str(plan.runtime.home)})
    if plan.runtime.platform == "wsl" and host_os == "nt":
        raise UnsupportedRuntimeApplyError(
            "Run hermes-cursor-native install inside WSL; Windows will not mutate Linux state"
        )
    hermes = Path(plan.runtime.executable)  # type: ignore[arg-type]
    if not hermes.is_file():
        raise InstallerError("Approved Hermes executable no longer exists")
    source = Path(plan.runtime.source_root) if plan.runtime.source_root is not None else Path(".")
    actual_executable_sha256 = hashlib.sha256(hermes.read_bytes()).hexdigest()
    if not plan.executable_sha256 or not hmac.compare_digest(
        actual_executable_sha256, plan.executable_sha256
    ):
        raise InstallerError("Approved Hermes executable changed after approval")
    live_version, _live_source = executable_probe(plan.runtime)
    if live_version != plan.runtime.version:
        raise InstallerError("Hermes executable identity changed after approval")

    stamp = timestamp()
    config_path: Path | None = None
    config_backup: Path | None = None
    config_existed = False
    backup_root = Path(plan.runtime.home) / "cursor-native" / "backups" / stamp
    plugin_backup: Path | None = None
    plugin_mutated = False
    plugin_path = Path(plan.runtime.home) / "plugins" / "model-providers" / "cursor"
    bridge_backup: Path | None = None
    bridge_mutated = False
    bridge_root = Path(plan.runtime.home) / "cursor-sdk-bridge"
    profile_args = ["-p", plan.profile]
    notes: list[str] = []

    try:
        if plugin_path.exists() or plugin_path.is_symlink():
            backup_root.mkdir(parents=True, exist_ok=True)
            plugin_backup = Path(tempfile.mkdtemp(prefix="plugin-", dir=backup_root)) / "cursor"
            plugin_path.rename(plugin_backup)
        plugin_mutated = True
        plugin_path = deploy_plugin(package_root, Path(plan.runtime.home))

        payload = download(plan.artifact["url"])
        verify_sha256(payload, plan.artifact["sha256"])
        bridge_mutated = True
        if bridge_root.exists():
            backup_root.mkdir(parents=True, exist_ok=True)
            bridge_backup = backup_root / "bridge"
            if bridge_backup.exists():
                shutil.rmtree(bridge_backup)
            shutil.move(str(bridge_root), str(bridge_backup))
        safe_extract_tar(payload, bridge_root)
        bridge = _find_bridge(bridge_root, plan.runtime.platform)

        config_result = _checked(run, [str(hermes), *profile_args, "config", "path"], source)
        reported_config = config_result.stdout.strip().splitlines()
        if reported_config:
            config_path = Path(reported_config[-1].strip())
            config_existed = config_path.is_file()
            if config_existed:
                backup_root.mkdir(parents=True, exist_ok=True)
                config_backup = backup_root / "config.yaml"
                shutil.copy2(config_path, config_backup)

        config_prefix = [str(hermes), *profile_args, "config", "set"]
        bridge_settings = (
            ("cursor_bridge.command", str(bridge)),
            ("cursor_bridge.tool_mode", "loop"),
            ("cursor_bridge.builtin_tools", "false"),
        )
        if plan.switch_default_model:
            bridge_settings = (
                *bridge_settings,
                ("model.provider", "cursor"),
                ("model.default", "composer-2.5"),
                ("model.context_length", "200000"),
            )
        for key, value in bridge_settings:
            _checked(run, [*config_prefix, key, value], source)

        if plan.run_oauth:
            run_cursor_oauth(run, hermes, source, Path(plan.runtime.home), package_root)
        else:
            notes.append("oauth skipped; run `hermes-cursor-native login` when ready")

        _checked(run, [str(hermes), *profile_args, "auth", "status", "cursor"], source)
        receipt = collect_receipt(
            plan.runtime, bridge_path=bridge, profile=plan.profile, notes=tuple(notes),
        )
        if not receipt.contract_checks.get("plugin_registered"):
            raise InstallerError("Post-install verification failed: cursor plugin not registered")
        if not receipt.contract_checks.get("client_contract"):
            raise InstallerError("Post-install verification failed: client contract checks failed")
        return InstallResult(bridge, plugin_path, config_backup, receipt)
    except BaseException as exc:
        rollback_errors: list[str] = []
        if config_path is not None:
            try:
                if config_existed and config_backup is not None and config_backup.is_file():
                    shutil.copy2(config_backup, config_path)
                elif not config_existed and config_path.exists():
                    config_path.unlink()
            except OSError as rollback_exc:
                rollback_errors.append(f"config restore failed: {rollback_exc}")
        if bridge_mutated:
            try:
                if bridge_root.exists():
                    shutil.rmtree(bridge_root)
                if bridge_backup is not None and bridge_backup.exists():
                    bridge_root.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(bridge_backup), str(bridge_root))
            except OSError as rollback_exc:
                rollback_errors.append(f"bridge restore failed: {rollback_exc}")
        if plugin_mutated:
            try:
                if plugin_path.is_symlink() or plugin_path.is_file():
                    plugin_path.unlink()
                elif plugin_path.exists():
                    shutil.rmtree(plugin_path)
                if plugin_backup is not None:
                    plugin_backup.rename(plugin_path)
            except OSError as rollback_exc:
                rollback_errors.append(f"plugin restore failed: {rollback_exc}")
        if rollback_errors:
            raise InstallerError("; ".join(rollback_errors)) from exc
        raise
