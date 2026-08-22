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
    git_state: GitState | None,
    architecture: str,
    provider_installed: bool = False,
    profile_exists: bool = True,
) -> InstallPlan:
    if not runtime.usable or runtime.source_root is None or runtime.executable is None:
        raise InstallBlockedError(f"Hermes runtime {runtime.runtime_id!r} is not usable")
    if runtime.version not in manifest.supported_hermes:
        supported = ", ".join(manifest.supported_hermes)
        raise InstallBlockedError(
            f"Hermes {runtime.version or 'unknown'} is unsupported; tested versions: {supported}"
        )
    if profile != "default" and not profile_exists:
        raise InstallBlockedError(
            f"Hermes profile {profile!r} does not exist; create it separately before install"
        )
    if git_state is None:
        raise InstallBlockedError(
            "A Git-backed Hermes source checkout is required for alpha patch mode"
        )
    if not git_state.clean:
        raise InstallBlockedError("Hermes source checkout is dirty; commit or stash changes first")
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

    artifact_key = f"{_artifact_platform(runtime.platform)}-{architecture}"
    artifact = manifest.artifacts.get(artifact_key)
    if artifact is None:
        raise InstallBlockedError(f"No verified bridge artifact for {artifact_key}")

    executable_sha256 = ""
    if isinstance(runtime.executable, Path) and runtime.executable.is_file():
        executable_sha256 = hashlib.sha256(runtime.executable.read_bytes()).hexdigest()

    operations = (
        InstallOperation("backup", "Create a rollback reference and config snapshot"),
        InstallOperation(
            "branch", "Create or update the maintained cursor-provider-deployed branch"
        ),
        InstallOperation("patch", "Apply the versioned Cursor provider patch series"),
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
        original_branch=git_state.branch,
        original_head=git_state.head,
        executable_sha256=executable_sha256,
        operations=operations,
    )
