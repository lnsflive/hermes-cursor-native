from __future__ import annotations

import pytest

from hermes_cursor_native.preflight import detect_architecture


@pytest.mark.parametrize("machine", ["x86_64", "amd64", "X64"])
def test_detect_architecture_accepts_known_x64_aliases(monkeypatch, machine: str) -> None:
    monkeypatch.setattr("platform.machine", lambda: machine)
    assert detect_architecture() == "x64"


def test_detect_architecture_rejects_unknown_architecture(monkeypatch) -> None:
    monkeypatch.setattr("platform.machine", lambda: "riscv64")
    with pytest.raises(RuntimeError, match="Unsupported architecture"):
        detect_architecture()
