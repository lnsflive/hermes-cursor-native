"""Versioned install-manifest loading."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .install_plan import InstallManifest

_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")
_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40}")
_SUPPORTED_PATCH_SERIES = (
    "0001-feat-providers-Cursor-subscription-support-via-the-o.patch",
    "0002-fix-cursor-support-SDK-bridge-on-Windows.patch",
    "0003-fix-cli-select-provider-default-model-on-override.patch",
    "0004-fix-cursor-harden-bridge-trust-boundaries.patch",
)


def _basename(value: object, label: str, suffix: str = "") -> str:
    name = str(value)
    if not name or "/" in name or "\\" in name or Path(name).name != name:
        raise ValueError(f"Unsafe {label}: {name!r}")
    if suffix and not name.endswith(suffix):
        raise ValueError(f"Invalid {label}: {name!r}")
    return name


def _validate_manifest(payload: dict) -> None:
    bases = payload.get("base_commits")
    if not isinstance(bases, list) or not bases or any(
        _COMMIT_RE.fullmatch(str(item)) is None for item in bases
    ):
        raise ValueError("Invalid base commit in install manifest")

    patches = payload.get("patch_series")
    if not isinstance(patches, list) or not patches:
        raise ValueError("Missing patch series")
    names = [_basename(item, "patch name", ".patch") for item in patches]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate patch name in install manifest")
    if tuple(names) != _SUPPORTED_PATCH_SERIES:
        raise ValueError("Unsupported patch series or patch order")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("Missing bridge artifacts")
    for artifact in artifacts.values():
        if not isinstance(artifact, dict):
            raise ValueError("Invalid bridge artifact entry")
        _basename(artifact.get("filename", ""), "artifact filename")
        if _SHA256_RE.fullmatch(str(artifact.get("sha256", ""))) is None:
            raise ValueError("Invalid artifact SHA256")
        if not str(artifact.get("url", "")).startswith("https://"):
            raise ValueError("Artifact URL must use HTTPS")

    provider_hashes = payload.get("provider_file_sha256")
    if not isinstance(provider_hashes, dict) or not provider_hashes:
        raise ValueError("Missing provider file hashes")
    for relative, digest in provider_hashes.items():
        path = str(relative)
        if not path or "\\" in path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"Unsafe provider file path: {path!r}")
        if _SHA256_RE.fullmatch(str(digest)) is None:
            raise ValueError(f"Invalid provider SHA256 for {path}")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def package_data_root() -> Path:
    installed = Path(__file__).resolve().parent
    if (installed / "install-manifest.json").is_file():
        return installed
    return repository_root()


def default_manifest_path() -> Path:
    return package_data_root() / "install-manifest.json"


def load_manifest(path: Path | None = None) -> InstallManifest:
    manifest_path = path or default_manifest_path()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"Unsupported install manifest schema: {payload.get('schema_version')!r}")
    _validate_manifest(payload)
    return InstallManifest.from_dict(payload)
