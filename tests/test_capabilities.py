from __future__ import annotations

from pathlib import Path

from hermes_cursor_native.capabilities import probe_runtime
from hermes_cursor_native.discovery import Runtime


def test_live_hermes_0211_reports_plugin_seam_without_sdkbridge_rail() -> None:
    source = Path("/root/.hermes/hermes-agent")
    if not (source / "providers" / "base.py").is_file():
        return
    runtime = Runtime(
        runtime_id="posix-current",
        surfaces=("cli",),
        platform="linux",
        home=Path("/root/.hermes"),
        source_root=source,
        executable=source / "venv/bin/hermes",
        version="0.21.1",
        usable=True,
        status="active",
    )
    report = probe_runtime(runtime)
    assert report.plugin_seam is True
    assert report.provider_supplied_client is True
    assert report.plugin_ready is True
    assert report.streaming_sdkbridge_rail is False
