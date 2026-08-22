from __future__ import annotations

from pathlib import Path

from hermes_cursor_native.discovery import Runtime
from hermes_cursor_native.rendering import render_runtime_table


def test_runtime_table_shows_active_legacy_and_remote_details() -> None:
    table = render_runtime_table(
        [
            Runtime(
                "windows-current",
                ("cli", "desktop"),
                "windows",
                Path("C:/Hermes"),
                Path("C:/Hermes/hermes-agent"),
                Path("C:/Hermes/hermes-agent/venv/Scripts/hermes.exe"),
                "0.20.5",
                True,
                "active",
            ),
            Runtime(
                "windows-legacy",
                ("legacy",),
                "windows",
                Path("C:/Users/test/.hermes"),
                None,
                None,
                "",
                False,
                "legacy/inactive",
            ),
        ]
    )

    assert "windows-current" in table
    assert "cli,desktop" in table
    assert "0.20.5" in table
    assert "windows-legacy" in table
    assert "legacy/inactive" in table
