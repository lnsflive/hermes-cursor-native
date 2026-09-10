from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_cursor_native.manifest import default_manifest_path, load_manifest


def test_repository_manifest_loads_bridge_artifacts() -> None:
    manifest = load_manifest(default_manifest_path())
    assert manifest.version
    assert manifest.artifacts["linux-x64"]["url"].startswith("https://")


def test_manifest_rejects_invalid_artifact_hash(tmp_path: Path) -> None:
    payload = json.loads(default_manifest_path().read_text(encoding="utf-8"))
    payload["artifacts"]["linux-x64"]["sha256"] = "bad"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256"):
        load_manifest(path)
