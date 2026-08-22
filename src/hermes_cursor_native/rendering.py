"""Human-readable output helpers."""

from __future__ import annotations

from collections.abc import Sequence

from .discovery import Runtime


def render_runtime_table(runtimes: Sequence[Runtime]) -> str:
    headers = ("RUNTIME", "SURFACES", "PLATFORM", "VERSION", "STATUS", "SOURCE")
    rows = [
        (
            runtime.runtime_id,
            ",".join(runtime.surfaces),
            runtime.platform,
            runtime.version or "-",
            runtime.status,
            str(runtime.source_root or "-"),
        )
        for runtime in runtimes
    ]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def format_row(row: tuple[str, ...]) -> str:
        return "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))

    output = [format_row(headers), format_row(tuple("-" * width for width in widths))]
    output.extend(format_row(row) for row in rows)
    return "\n".join(output)
