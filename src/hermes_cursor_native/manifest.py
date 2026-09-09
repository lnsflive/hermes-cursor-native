"""Install-manifest loading for the Cursor model-provider plugin."""

from __future__ import annotations

import json
import re
from pathlib import Path

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InstallManifest:
    version: str
    artifacts: dict[str, dict[str, str]]
    bridge_version: str = ""
    plugin_commit: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> InstallManifest:
        return cls(
            version=str(payload["version"]),
            artifacts={
                str(key): {str(k): str(v) for k, v in value.items()}
                for key, value in payload["artifacts"].items()
            },
            bridge_version=str(payload.get("bridge_version", "")),
            plugin_commit=str(payload.get("plugin_commit", "")),
        )

_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


def _basename(value: object, label: str, suffix: str = "") -> str:
    name = str(value)
    if not name or "/" in name or "\\" in name or Path(name).name != name:
        raise ValueError(f"Unsafe {label}: {name!r}")
    if suffix and not name.endswith(suffix):
        raise ValueError(f"Invalid {label}: {name!r}")
    return name


def _validate_manifest(payload: dict) -> None:
    if payload.get("schema_version") not in {1, 2}:
        raise ValueError(f"Unsupported install manifest schema: {payload.get('schema_version')!r}")

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


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def package_data_root() -> Path:
    repo = repository_root()
    if (repo / "plugin" / "model-providers" / "cursor").is_dir():
        return repo
    installed = Path(__file__).resolve().parent
    if (installed / "plugin" / "model-providers" / "cursor").is_dir():
        return installed
    if (installed / "install-manifest.json").is_file():
        return installed
    return repo


def default_manifest_path() -> Path:
    return package_data_root() / "install-manifest.json"


def load_manifest(path: Path | None = None) -> InstallManifest:
    manifest_path = path or default_manifest_path()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_manifest(payload)
    return InstallManifest.from_dict(payload)
