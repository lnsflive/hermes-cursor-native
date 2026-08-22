"""Security-critical installer primitives."""

from __future__ import annotations

import hashlib
import hmac
import io
import os
import secrets
import shutil
import subprocess
import tarfile
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .discovery import Runtime
from .install_plan import GitState, InstallPlan
from .preflight import probe_git_state, provider_installation_complete


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
    branch: str
    backup_branch: str
    bridge_path: Path
    config_backup: Path | None


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


def validate_smoke_output(result: CommandResult, marker: str, label: str) -> None:
    if marker not in result.stdout:
        raise InstallerError(f"{label} smoke did not return expected marker {marker!r}")


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
    """Extract regular files/directories only, with strict containment bounds."""

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


def run_command(args: list[str], cwd: Path, interactive: bool = False) -> CommandResult:
    if interactive:
        completed = subprocess.run(args, cwd=cwd, check=False)
        return CommandResult(completed.returncode, "", "")
    completed = subprocess.run(
        args,
        cwd=cwd,
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


def _tool_nonce() -> str:
    return secrets.token_hex(16)


def execute_install_plan(
    plan: InstallPlan,
    *,
    package_root: Path,
    approved: bool,
    run: CommandRunner = run_command,
    download: Downloader = download_url,
    timestamp: Callable[[], str] = _timestamp,
    host_os: str = os.name,
    provider_validator: Callable[[Path, Mapping[str, str]], bool] = (
        provider_installation_complete
    ),
    git_probe: Callable[[Path], GitState] = probe_git_state,
    nonce_factory: Callable[[], str] = _tool_nonce,
    executable_probe: Callable[[Runtime], tuple[str, Path | None]] = (
        probe_executable_identity
    ),
) -> InstallResult:
    """Apply an approved plan. Credentials never cross the command argument boundary."""

    require_approval(approved)
    if plan.runtime.platform == "wsl" and host_os == "nt":
        raise UnsupportedRuntimeApplyError(
            "Run hermes-cursor-native install inside WSL; Windows will not mutate Linux state"
        )
    source = Path(plan.runtime.source_root)  # type: ignore[arg-type]
    hermes = Path(plan.runtime.executable)  # type: ignore[arg-type]
    if not source.is_dir() or not hermes.is_file():
        raise InstallerError("Approved Hermes source or executable no longer exists")
    actual_executable_sha256 = hashlib.sha256(hermes.read_bytes()).hexdigest()
    if not plan.executable_sha256 or not hmac.compare_digest(
        actual_executable_sha256, plan.executable_sha256
    ):
        raise InstallerError("Approved Hermes executable changed after approval")
    live_version, live_source = executable_probe(plan.runtime)
    if (
        live_version != plan.runtime.version
        or live_source is None
        or live_source.resolve() != source.resolve()
    ):
        raise InstallerError("Hermes executable identity changed after approval")
    live_git = git_probe(source)
    if (
        not live_git.clean
        or live_git.branch != plan.original_branch
        or live_git.head != plan.original_head
    ):
        raise InstallerError(
            "Hermes Git state changed after approval; run discovery and dry-run again"
        )
    stamp = timestamp()
    backup_branch = f"backup/hermes-cursor-native-{stamp}"
    target_branch = "cursor-provider-deployed"
    config_path: Path | None = None
    config_backup: Path | None = None
    config_existed = False
    tool_probe_path: Path | None = None
    backup_root = Path(plan.runtime.home) / "cursor-native" / "backups" / stamp
    bridge_backup: Path | None = None
    bridge_mutated = False
    backup_created = False
    am_in_progress = False
    bridge_root = (
        Path(plan.runtime.home) / "cursor-native" / "bridge" / plan.manifest_version
    )

    existing = run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{target_branch}"],
        source,
        False,
    )
    if existing.returncode not in {0, 1}:
        raise InstallerError(
            "Could not inspect deployment branch: "
            f"{existing.stderr.strip() or existing.stdout.strip()}"
        )
    target_head = ""
    if existing.returncode == 0:
        current_head = _checked(run, ["git", "rev-parse", "HEAD"], source).stdout.strip()
        target_head = _checked(
            run, ["git", "rev-parse", target_branch], source
        ).stdout.strip()
        if current_head != target_head:
            raise InstallerError(
                f"Existing {target_branch} diverges from current HEAD; reconcile it manually"
            )
    target_existed = existing.returncode == 0

    try:
        _checked(run, ["git", "branch", backup_branch, "HEAD"], source)
        backup_created = True
        if target_existed:
            _checked(run, ["git", "switch", target_branch], source)
        else:
            _checked(run, ["git", "switch", "-c", target_branch], source)

        provider_marker = source / "agent" / "cursor_bridge_client.py"
        provider_complete = provider_validator(source, plan.provider_file_sha256)
        if provider_marker.exists() and not provider_complete:
            raise InstallerError(
                "Partial or unhardened Cursor provider detected; restore a clean base first"
            )
        if not provider_complete:
            patch_root = package_root / "patches" / "hermes" / plan.runtime.version
            for patch_name in plan.patch_series:
                patch_path = patch_root / patch_name
                if not patch_path.is_file():
                    raise InstallerError(f"Patch file is missing: {patch_path}")
                am_in_progress = True
                _checked(run, ["git", "am", str(patch_path)], source)
                am_in_progress = False
            if not provider_validator(source, plan.provider_file_sha256):
                raise InstallerError(
                    "Applied patch series did not produce a complete hardened provider"
                )

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

        profile_args = [] if plan.profile == "default" else ["-p", plan.profile]
        config_result = _checked(
            run, [str(hermes), *profile_args, "config", "path"], source
        )
        reported_config = config_result.stdout.strip().splitlines()
        if reported_config:
            config_path = Path(reported_config[-1].strip())
            config_existed = config_path.is_file()
            if config_existed:
                backup_root.mkdir(parents=True, exist_ok=True)
                config_backup = backup_root / "config.yaml"
                shutil.copy2(config_path, config_backup)

        config_prefix = [str(hermes), *profile_args, "config", "set"]
        for key, value in (
            ("model.provider", "cursor"),
            ("model.default", "composer-2.5"),
            ("model.context_length", "200000"),
            ("cursor_bridge.command", str(bridge)),
            ("cursor_bridge.tool_mode", "loop"),
            ("cursor_bridge.builtin_tools", "false"),
            ("updates.parked_branch_strategy", "update_in_place"),
        ):
            _checked(run, [*config_prefix, key, value], source)

        _checked(run, [str(hermes), "cursor", "login"], source, True)

        smoke_prefix = [str(hermes), *profile_args, "chat", "--provider", "cursor"]
        backup_root.mkdir(parents=True, exist_ok=True)
        tool_nonce = nonce_factory()
        tool_probe_path = backup_root / "tool-smoke.txt"
        tool_probe_path.write_text(tool_nonce, encoding="utf-8")
        smokes = (
            (
                [
                    *smoke_prefix,
                    "-m",
                    "composer-2.5",
                    "-q",
                    "Reply exactly COMPOSER_OK",
                    "-Q",
                ],
                "COMPOSER_OK",
                "Composer",
            ),
            (
                [
                    *smoke_prefix,
                    "-m",
                    "grok-4.6",
                    "-q",
                    "Reply exactly GROK_OK",
                    "-Q",
                ],
                "GROK_OK",
                "Grok",
            ),
            (
                [*smoke_prefix, "-q", "Reply exactly AUTO_OK", "-Q"],
                "AUTO_OK",
                "automatic routing",
            ),
            (
                [
                    *smoke_prefix,
                    "-m",
                    "composer-2.5",
                    "-t",
                    "terminal",
                    "-q",
                    f"Use the Hermes terminal tool to read {tool_probe_path}. "
                    "Reply exactly with the file contents.",
                    "-Q",
                ],
                tool_nonce,
                "Hermes terminal tool",
            ),
        )
        for command, marker, label in smokes:
            result = _checked(run, command, source)
            validate_smoke_output(result, marker, label)
        tool_probe_path.unlink()
        tool_probe_path = None
    except BaseException as exc:
        rollback_errors: list[str] = []
        if tool_probe_path is not None and tool_probe_path.exists():
            try:
                tool_probe_path.unlink()
            except OSError as rollback_exc:
                rollback_errors.append(f"tool probe cleanup failed: {rollback_exc}")
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
        rollback_commands: list[list[str]] = []
        if am_in_progress:
            rollback_commands.append(["git", "am", "--abort"])
        if backup_created:
            if plan.original_branch:
                rollback_commands.append(["git", "switch", plan.original_branch])
            else:
                rollback_commands.append(["git", "switch", "--detach", plan.original_head])
        git_restore_ok = True
        for command in rollback_commands:
            try:
                result = run(command, source, False)
                if result.returncode != 0:
                    git_restore_ok = False
                    rollback_errors.append(
                        f"rollback command failed: {' '.join(command)}: "
                        f"{result.stderr.strip() or result.stdout.strip()}"
                    )
            except BaseException as rollback_exc:
                git_restore_ok = False
                rollback_errors.append(
                    f"rollback command raised: {' '.join(command)}: {rollback_exc}"
                )
        if backup_created and git_restore_ok and not target_existed:
            created = run(
                [
                    "git",
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{target_branch}",
                ],
                source,
                False,
            )
            if created.returncode == 0:
                result = run(["git", "branch", "-D", target_branch], source, False)
                if result.returncode != 0:
                    rollback_errors.append(
                        f"rollback command failed: git branch -D {target_branch}: "
                        f"{result.stderr.strip() or result.stdout.strip()}"
                    )
            elif created.returncode != 1:
                rollback_errors.append(
                    "rollback branch inspection failed: "
                    f"{created.stderr.strip() or created.stdout.strip()}"
                )
        elif backup_created and git_restore_ok and target_existed:
            if plan.original_branch == target_branch:
                restore_target = ["git", "reset", "--hard", target_head]
            else:
                restore_target = ["git", "branch", "-f", target_branch, target_head]
            try:
                result = run(restore_target, source, False)
                if result.returncode != 0:
                    rollback_errors.append(
                        f"deployment branch restore failed: {' '.join(restore_target)}: "
                        f"{result.stderr.strip() or result.stdout.strip()}"
                    )
            except BaseException as rollback_exc:
                rollback_errors.append(
                    f"deployment branch restore raised: {' '.join(restore_target)}: "
                    f"{rollback_exc}"
                )
        if rollback_errors:
            raise InstallerError("; ".join(rollback_errors)) from exc
        raise

    return InstallResult(target_branch, backup_branch, bridge, config_backup)
