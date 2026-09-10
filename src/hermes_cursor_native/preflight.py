"""Local installation preflight helpers."""

from __future__ import annotations

import platform


def detect_architecture() -> str:
    machine = platform.machine().casefold()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine in {"x86_64", "amd64", "x64"}:
        return "x64"
    raise RuntimeError(f"Unsupported architecture: {machine or 'unknown'}")
