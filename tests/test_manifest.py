from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_cursor_native.manifest import load_manifest


def test_repository_manifest_references_existing_patches_and_valid_hashes() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = load_manifest(root / "install-manifest.json")
    patch_root = root / "patches/hermes/0.20.5"

    assert manifest.version == "0.1.0a1"
    assert manifest.supported_hermes == ("0.20.5",)
    assert all((patch_root / name).is_file() for name in manifest.patch_series)
    assert all(len(artifact["sha256"]) == 64 for artifact in manifest.artifacts.values())
    assert all(artifact["url"].startswith("https://") for artifact in manifest.artifacts.values())
    assert len(manifest.provider_file_sha256) == 25
    assert all(len(digest) == 64 for digest in manifest.provider_file_sha256.values())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update(patch_series=["../escape.patch"]), "patch name"),
        (
            lambda payload: payload["artifacts"]["windows-x64"].update(sha256="bad"),
            "artifact SHA256",
        ),
        (
            lambda payload: payload["artifacts"]["windows-x64"].update(
                url="http://example.invalid/bridge"
            ),
            "HTTPS",
        ),
        (lambda payload: payload.update(base_commits=["short"]), "base commit"),
        (
            lambda payload: payload.update(
                patch_series=list(reversed(payload["patch_series"]))
            ),
            "patch series",
        ),
    ],
)
def test_manifest_rejects_unsafe_structure(tmp_path: Path, mutation, message: str) -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "install-manifest.json").read_text(encoding="utf-8"))
    mutation(payload)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_manifest(path)
