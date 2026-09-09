"""Fail-closed installation planning.

Planning is pure: it describes every intended write before an executor performs
any mutation. OAuth credentials are never included in plan data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .capabilities import CapabilityReport, probe_runtime
from .discovery import Runtime


class InstallBlockedError(RuntimeError):
    """Raised when installation preconditions are not satisfied."""


@dataclass(frozen=True)
class GitState:
    clean: bool
    branch: str
    head: str


@dataclass(frozen=True)
class InstallManifest:
    version: str
    supported_hermes: tuple[str, ...]
    base_commits: tuple[str, ...]
    artifacts: dict[str, dict[str, str]]
    patch_series: tuple[str, ...]
    provider_file_sha256: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> InstallManifest:
        return cls(
            version=str(payload["version"]),
            supported_hermes=tuple(str(item) for item in payload["supported_hermes"]),
            base_commits=tuple(str(item) for item in payload.get("base_commits", [])),
            artifacts={
                str(key): {str(k): str(v) for k, v in value.items()}
                for key, value in payload["artifacts"].items()
            },
            patch_series=tuple(str(item) for item in payload["patch_series"]),
            provider_file_sha256={
                str(key): str(value).lower()
                for key, value in payload["provider_file_sha256"].items()
            },
        )


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
    patch_series: tuple[str, ...]
    provider_file_sha256: dict[str, str]
    original_branch: str
    original_head: str
    executable_sha256: str
    operations: tuple[InstallOperation, ...]
    install_mode: str
    capabilities: CapabilityReport
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
            "provider_supplied_client": caps["provider_supplied_client"],
            "streaming_sdkbridge_rail": caps["streaming_sdkbridge_rail"],
            "cursor_bridge_config": caps["cursor_bridge_config"],
            "plugin_ready": self.capabilities.plugin_ready,
            "fully_ready": self.capabilities.fully_ready,
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


def _legacy_patch_eligible(
    *,
    runtime: Runtime,
    manifest: InstallManifest,
    git_state: GitState | None,
    provider_installed: bool,
) -> bool:
    if git_state is None or not git_state.clean:
        return False
    if runtime.version not in manifest.supported_hermes:
        return False
    maintained_branch = git_state.branch == "cursor-provider-deployed"
    if maintained_branch and not provider_installed:
        return False
    if maintained_branch:
        return True
    if not manifest.base_commits:
        return True
    return any(
        git_state.head.startswith(base) or base.startswith(git_state.head)
        for base in manifest.base_commits
    )


def build_install_plan(
    *,
    runtime: Runtime,
    manifest: InstallManifest,
    profile: str,
    git_state: GitState | None,
    architecture: str,
    provider_installed: bool = False,
    profile_exists: bool = True,
    capability_report: CapabilityReport | None = None,
) -> InstallPlan:
    if not runtime.usable or runtime.executable is None:
        raise InstallBlockedError(f"Hermes runtime {runtime.runtime_id!r} is not usable")
    if profile != "default" and not profile_exists:
        raise InstallBlockedError(
            f"Hermes profile {profile!r} does not exist; create it separately before install"
        )

    capabilities = capability_report or probe_runtime(runtime)
    plugin_mode = capabilities.plugin_ready
    patch_mode = _legacy_patch_eligible(
        runtime=runtime,
        manifest=manifest,
        git_state=git_state,
        provider_installed=provider_installed,
    )
    if patch_mode:
        install_mode = "patch"
    elif plugin_mode:
        install_mode = "plugin"
    else:
        if runtime.version in manifest.supported_hermes:
            if git_state is None:
                raise InstallBlockedError(
                    "A Git-backed Hermes source checkout is required for legacy patch mode"
                )
            if not git_state.clean:
                raise InstallBlockedError(
                    "Hermes source checkout is dirty; commit or stash changes first"
                )
            maintained_branch = git_state.branch == "cursor-provider-deployed"
            if maintained_branch and not provider_installed:
                raise InstallBlockedError(
                    "Maintained branch requires complete provider validation before reconfiguration"
                )
            compatible_base = any(
                git_state.head.startswith(base) or base.startswith(git_state.head)
                for base in manifest.base_commits
            )
            if not maintained_branch and manifest.base_commits and not compatible_base:
                expected = ", ".join(manifest.base_commits)
                raise InstallBlockedError(
                    f"Hermes base commit {git_state.head} is not supported; expected one of: {expected}"
                )
        blockers = ", ".join(capabilities.blockers()) or "unknown capability gap"
        raise InstallBlockedError(
            f"Hermes {runtime.version or 'unknown'} lacks required Cursor provider interfaces: {blockers}"
        )
    if install_mode == "patch":
        if runtime.source_root is None:
            raise InstallBlockedError("Patch mode requires a Git-backed Hermes source checkout")
        if git_state is None:
            raise InstallBlockedError("Patch mode requires readable Git state for the checkout")
        if not git_state.clean:
            raise InstallBlockedError("Hermes source checkout is dirty; commit or stash changes first")

    artifact_key = f"{_artifact_platform(runtime.platform)}-{architecture}"
    artifact = manifest.artifacts.get(artifact_key)
    if artifact is None:
        raise InstallBlockedError(f"No verified bridge artifact for {artifact_key}")

    executable_sha256 = ""
    if isinstance(runtime.executable, Path) and runtime.executable.is_file():
        executable_sha256 = hashlib.sha256(runtime.executable.read_bytes()).hexdigest()

    if install_mode == "plugin":
        operations = (
            InstallOperation("backup", "Snapshot profile config before provider install"),
            InstallOperation(
                "plugin",
                "Install the Cursor model-provider plugin into $HERMES_HOME/plugins/model-providers/cursor",
            ),
            InstallOperation("bridge", f"Download and verify {artifact['filename']}"),
            InstallOperation("configure", f"Configure Hermes profile {profile!r} with provider cursor"),
            InstallOperation("oauth", "Launch Cursor browser OAuth without exposing credentials"),
            InstallOperation("verify", "Verify provider registration and bridge connectivity"),
        )
        if not capabilities.fully_ready:
            operations = (
                *operations,
                InstallOperation(
                    "note",
                    "Core sdkbridge streaming rails missing; install may work but turns can mis-stream",
                ),
            )
    else:
        operations = (
            InstallOperation("backup", "Create a rollback reference and config snapshot"),
            InstallOperation(
                "branch", "Create or update the maintained cursor-provider-deployed branch"
            ),
            InstallOperation("patch", "Apply the legacy versioned Cursor provider patch series"),
            InstallOperation("bridge", f"Download and verify {artifact['filename']}"),
            InstallOperation("configure", f"Configure Hermes profile {profile!r} in loop tool mode"),
            InstallOperation("oauth", "Launch Cursor browser OAuth without exposing credentials"),
            InstallOperation(
                "verify", "Run Composer, Grok, automatic-routing, and hidden-nonce tool smokes"
            ),
        )

    return InstallPlan(
        runtime=runtime,
        profile=profile,
        manifest_version=manifest.version,
        artifact_key=artifact_key,
        artifact=dict(artifact),
        patch_series=manifest.patch_series,
        provider_file_sha256=dict(manifest.provider_file_sha256),
        original_branch=git_state.branch if git_state is not None else "",
        original_head=git_state.head if git_state is not None else "",
        executable_sha256=executable_sha256,
        operations=operations,
        install_mode=install_mode,
        capabilities=capabilities,
    )
