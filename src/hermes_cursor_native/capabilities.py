"""Runtime capability probes for Hermes Cursor Native.

Install planning keys off interface checks (provider plugin seam, custom client
hooks, streaming rails) rather than an exact Hermes version string.
"""

from __future__ import annotations

import inspect
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .discovery import Runtime


@dataclass(frozen=True)
class CapabilityReport:
    """Outcome of probing one Hermes estate."""

    runtime_id: str
    hermes_version: str
    source_root: Path | None
    plugin_seam: bool
    provider_supplied_client: bool
    streaming_sdkbridge_rail: bool
    cursor_bridge_config: bool
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def plugin_ready(self) -> bool:
        """Enough surface exists to install via the model-provider plugin path."""
        return self.plugin_seam and self.provider_supplied_client

    @property
    def fully_ready(self) -> bool:
        """Plugin path plus core rails that keep Cursor turns stable."""
        return self.plugin_ready and self.streaming_sdkbridge_rail

    def blockers(self) -> list[str]:
        items: list[str] = []
        if not self.plugin_seam:
            items.append("ProviderProfile.create_client seam missing")
        if not self.provider_supplied_client:
            items.append("agent runtime does not consult provider-supplied clients")
        if not self.streaming_sdkbridge_rail:
            items.append("turn streaming rail does not exclude sdkbridge:// transports")
        return items


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _probe_via_source(source_root: Path | None) -> CapabilityReport:
    version = ""
    notes: list[str] = []
    plugin_seam = False
    provider_supplied_client = False
    streaming_sdkbridge_rail = False
    cursor_bridge_config = False

    if source_root is None:
        return CapabilityReport(
            runtime_id="unknown",
            hermes_version=version,
            source_root=None,
            plugin_seam=False,
            provider_supplied_client=False,
            streaming_sdkbridge_rail=False,
            cursor_bridge_config=False,
            notes=("no source checkout to inspect",),
        )

    base = Path(source_root)
    providers_base = _read_text(base / "providers" / "base.py")
    plugin_seam = "def create_client" in providers_base

    runtime_helpers = _read_text(base / "agent" / "agent_runtime_helpers.py")
    provider_supplied_client = "_provider_supplied_client" in runtime_helpers

    turn_api = _read_text(base / "agent" / "turn_api_call.py")
    conversation = _read_text(base / "agent" / "conversation_loop.py")
    streaming_sdkbridge_rail = (
        "sdkbridge://" in turn_api
        or '"cursor"' in turn_api
        or "sdkbridge://" in conversation
        or '"cursor"' in conversation
    )

    defaults = _read_text(base / "hermes_cli" / "config_defaults.py")
    cursor_bridge_config = '"cursor_bridge"' in defaults

    if not plugin_seam:
        notes.append("upgrade Hermes or use a release with model-provider plugins")
    if plugin_seam and not provider_supplied_client:
        notes.append("provider plugins register but primary client seam is absent")
    if not streaming_sdkbridge_rail:
        notes.append(
            "sdkbridge streaming exclusion missing; turns may mis-stream until core catches up"
        )

    return CapabilityReport(
        runtime_id="inspected",
        hermes_version=version,
        source_root=base,
        plugin_seam=plugin_seam,
        provider_supplied_client=provider_supplied_client,
        streaming_sdkbridge_rail=streaming_sdkbridge_rail,
        cursor_bridge_config=cursor_bridge_config,
        notes=tuple(notes),
    )


def probe_runtime(runtime: Runtime) -> CapabilityReport:
    """Inspect the runtime's Hermes checkout and version output."""
    version = runtime.version
    report = _probe_via_source(
        Path(runtime.source_root) if runtime.source_root is not None else None
    )
    if runtime.executable is not None:
        try:
            completed = subprocess.run(
                [str(runtime.executable), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            if completed.returncode == 0:
                for line in f"{completed.stdout}\n{completed.stderr}".splitlines():
                    if "Hermes Agent v" in line:
                        version = line.split("Hermes Agent v", 1)[1].split()[0]
                        break
        except (OSError, subprocess.TimeoutExpired):
            pass

    return CapabilityReport(
        runtime_id=runtime.runtime_id,
        hermes_version=version or runtime.version,
        source_root=report.source_root,
        plugin_seam=report.plugin_seam,
        provider_supplied_client=report.provider_supplied_client,
        streaming_sdkbridge_rail=report.streaming_sdkbridge_rail,
        cursor_bridge_config=report.cursor_bridge_config,
        notes=report.notes,
    )


def provider_profile_create_client_callable() -> bool:
    """True when the installed hermes_cursor_native environment can import the seam."""
    try:
        from providers.base import ProviderProfile  # type: ignore[import-not-found]

        return callable(getattr(ProviderProfile, "create_client", None))
    except Exception:
        return False
