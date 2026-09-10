"""Fail-closed installation planning for the Cursor model-provider plugin."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .capabilities import CapabilityReport, probe_runtime
from .discovery import Runtime
from .manifest import InstallManifest


class InstallBlockedError(RuntimeError):
    """Raised when installation preconditions are not satisfied."""


def resolve_profile_home(hermes_home: Path, profile: str) -> Path:
    """Return the resolved profile estate root, rejecting symlink escapes."""
    validate_profile_name(profile)
    base = hermes_home.expanduser().resolve()
    if profile == "default":
        return base
    profiles_root = (base / "profiles").resolve()
    try:
        profiles_root.relative_to(base)
    except ValueError:
        raise InstallBlockedError(
            f"Hermes profiles directory resolves outside {base}"
        ) from None
    selected = (profiles_root / profile).resolve()
    try:
        selected.relative_to(profiles_root)
    except ValueError:
        raise InstallBlockedError(
            f"Hermes profile {profile!r} resolves outside {profiles_root}"
        ) from None
    return selected


def validate_profile_name(profile: str) -> None:
    """Reject profile values that escape ``<HERMES_HOME>/profiles`` when joined."""
    if profile == "default":
        return
    if not profile or profile in {".", ".."}:
        raise InstallBlockedError(f"Invalid Hermes profile name: {profile!r}")
    posix = PurePosixPath(profile)
    windows = PureWindowsPath(profile)
    if len(posix.parts) != 1 or len(windows.parts) != 1:
        raise InstallBlockedError(f"Invalid Hermes profile name: {profile!r}")
    if posix.is_absolute() or windows.is_absolute():
        raise InstallBlockedError(f"Invalid Hermes profile name: {profile!r}")
    if posix.parts[0] in {".", ".."} or windows.parts[0] in {".", ".."}:
        raise InstallBlockedError(f"Invalid Hermes profile name: {profile!r}")


@dataclass(frozen=True)
class InstallOperation:
    kind: str
    description: str


@dataclass(frozen=True)
class InstallPlan:
    runtime: Runtime
    profile: str
    manifest_version: str
    artifact_key: str
    artifact: dict[str, str]
    executable_sha256: str
    operations: tuple[InstallOperation, ...]
    capabilities: CapabilityReport
    switch_default_model: bool = False
    run_oauth: bool = False
    requires_approval: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["runtime"]["home"] = str(self.runtime.home)
        payload["runtime"]["source_root"] = (
            str(self.runtime.source_root) if self.runtime.source_root else None
        )
        payload["runtime"]["executable"] = (
            str(self.runtime.executable) if self.runtime.executable else None
        )
        caps = payload.pop("capabilities")
        payload["capabilities"] = {
            "runtime_id": caps["runtime_id"],
            "hermes_version": caps["hermes_version"],
            "source_root": str(caps["source_root"]) if caps["source_root"] else None,
            "plugin_seam": caps["plugin_seam"],
            "provider_client_seam": caps["provider_client_seam"],
            "plugin_registered": caps["plugin_registered"],
            "client_contract": caps["client_contract"],
            "interface_ready": self.capabilities.interface_ready,
            "plugin_ready": self.capabilities.plugin_ready,
            "blockers": self.capabilities.blockers(),
            "notes": list(caps["notes"]),
        }
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def _artifact_platform(platform: str) -> str:
    if platform == "windows":
        return "windows"
    if platform in {"wsl", "linux"} or platform.startswith("linux"):
        return "linux"
    if platform in {"darwin", "macos"}:
        return "macos"
    return platform


def build_install_plan(
    *,
    runtime: Runtime,
    manifest: InstallManifest,
    profile: str,
    architecture: str,
    profile_exists: bool = True,
    capability_report: CapabilityReport | None = None,
    switch_default_model: bool = False,
    run_oauth: bool = False,
) -> InstallPlan:
    validate_profile_name(profile)
    if not runtime.usable or runtime.executable is None:
        raise InstallBlockedError(f"Hermes runtime {runtime.runtime_id!r} is not usable")
    if profile != "default" and not profile_exists:
        raise InstallBlockedError(
            f"Hermes profile {profile!r} does not exist; create it separately before install"
        )

    capabilities = capability_report or probe_runtime(runtime)
    if not capabilities.plugin_ready:
        blockers = ", ".join(capabilities.blockers()) or "unknown capability gap"
        raise InstallBlockedError(
            f"Hermes {runtime.version or 'unknown'} is not ready for the Cursor plugin: {blockers}"
        )

    artifact_key = f"{_artifact_platform(runtime.platform)}-{architecture}"
    artifact = manifest.artifacts.get(artifact_key)
    if artifact is None:
        raise InstallBlockedError(f"No verified bridge artifact for {artifact_key}")

    executable_sha256 = ""
    if isinstance(runtime.executable, Path) and runtime.executable.is_file():
        executable_sha256 = hashlib.sha256(runtime.executable.read_bytes()).hexdigest()

    configure_note = (
        f"Switch profile {profile!r} default model to Cursor"
        if switch_default_model
        else f"Install bridge settings for profile {profile!r} without changing default model"
    )
    operations = (
        InstallOperation("backup", "Snapshot profile config before provider install"),
        InstallOperation(
            "plugin",
            "Install the Cursor model-provider plugin into "
            "$HERMES_HOME/plugins/model-providers/cursor",
        ),
        InstallOperation("bridge", f"Download and verify {artifact['filename']}"),
        InstallOperation("configure", configure_note),
        InstallOperation(
            "oauth",
            "Optional browser OAuth (skipped unless --oauth); never prints stored credentials",
        ),
        InstallOperation(
            "verify",
            "Verify plugin registration, auth status, and client streaming/tool contract",
        ),
    )

    return InstallPlan(
        runtime=runtime,
        profile=profile,
        manifest_version=manifest.version,
        artifact_key=artifact_key,
        artifact=dict(artifact),
        executable_sha256=executable_sha256,
        operations=operations,
        capabilities=capabilities,
        switch_default_model=switch_default_model,
        run_oauth=run_oauth,
    )
