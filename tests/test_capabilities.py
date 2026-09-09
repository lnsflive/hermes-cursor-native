from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cursor_native.capabilities import probe_runtime
from hermes_cursor_native.discovery import Runtime

HERMES_SOURCE = Path("/root/.hermes/hermes-agent")


@pytest.mark.skipif(not HERMES_SOURCE.is_dir(), reason="stock Hermes checkout not present")
def test_live_stock_hermes_passes_behavioral_capability_probe() -> None:
    runtime = Runtime(
        "posix-current",
        ("cli",),
        "linux",
        Path("/root/.hermes"),
        HERMES_SOURCE,
        HERMES_SOURCE / "venv/bin/hermes",
        "0.21.1",
        True,
        "active",
    )
    report = probe_runtime(runtime)
    assert report.plugin_seam is True
    assert report.provider_client_seam is True
    assert report.plugin_registered is True
    assert report.client_contract is True
    assert report.plugin_ready is True
