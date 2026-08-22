from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hermes_cursor_native.preflight import (
    _PROVIDER_FILES,
    detect_architecture,
    provider_installation_complete,
)

REQUIRED = list(_PROVIDER_FILES)


def test_provider_validation_rejects_partial_install(tmp_path: Path) -> None:
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent/cursor_bridge_client.py").write_text("partial", encoding="utf-8")

    assert provider_installation_complete(tmp_path, {}) is False


def test_provider_validation_requires_manifest_pinned_file_hashes(tmp_path: Path) -> None:
    for relative in REQUIRED:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("present", encoding="utf-8")

    (tmp_path / "agent/cursor_bridge_client.py").write_text(
        "_MAX_CALLBACK_BODY = 1024\nnot declared for this Hermes run",
        encoding="utf-8",
    )
    (tmp_path / "agent/cursor_bridge_transport.py").write_text(
        "inherit_credentials=False\nchecksum metadata unavailable",
        encoding="utf-8",
    )

    forged_hashes = {relative: "0" * 64 for relative in REQUIRED}

    def reader(root: Path, relative: str) -> bytes:
        return (root / relative).read_bytes()

    assert provider_installation_complete(tmp_path, forged_hashes, reader) is False

    actual_hashes = {
        relative: hashlib.sha256((tmp_path / relative).read_bytes()).hexdigest()
        for relative in REQUIRED
    }
    assert provider_installation_complete(tmp_path, actual_hashes, reader) is True


def test_provider_validation_hashes_canonical_git_blob_not_worktree_bytes(
    tmp_path: Path,
) -> None:
    expected = {relative: hashlib.sha256(b"canonical\n").hexdigest() for relative in REQUIRED}
    for relative in REQUIRED:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"canonical\r\n")

    assert provider_installation_complete(
        tmp_path,
        expected,
        lambda _root, _relative: b"canonical\n",
    )


@pytest.mark.parametrize("machine", ["x86_64", "amd64", "AMD64"])
def test_detect_architecture_accepts_known_x64_aliases(monkeypatch, machine: str) -> None:
    monkeypatch.setattr("platform.machine", lambda: machine)
    assert detect_architecture() == "x64"


def test_detect_architecture_rejects_unknown_architecture(monkeypatch) -> None:
    monkeypatch.setattr("platform.machine", lambda: "riscv64")
    with pytest.raises(RuntimeError, match="Unsupported architecture"):
        detect_architecture()
