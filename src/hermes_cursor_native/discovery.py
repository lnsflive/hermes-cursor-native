"""Runtime discovery primitives.

The installer treats every Hermes estate as independent until a probe proves
that two candidates resolve to the same backend checkout.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePath


class DiscoveryError(RuntimeError):
    """Base class for runtime discovery failures."""


class AmbiguousRuntimeError(DiscoveryError):
    """Raised when installation would require silently choosing a runtime."""


class RuntimeNotFoundError(DiscoveryError):
    """Raised when no usable runtime matches the requested target."""


@dataclass(frozen=True)
class Candidate:
    """A possible Hermes runtime before executable probing."""

    runtime_id: str
    surface: str
    platform: str
    home: PurePath
    source_root: PurePath | None
    executable: PurePath | None
    active_hint: bool = False


@dataclass(frozen=True)
class ProbeResult:
    """Result of invoking a candidate's own Hermes runtime."""

    usable: bool
    version: str = ""
    source_root: PurePath | None = None
    executable: PurePath | None = None


@dataclass(frozen=True)
class Runtime:
    """A classified, deduplicated Hermes backend."""

    runtime_id: str
    surfaces: tuple[str, ...]
    platform: str
    home: PurePath
    source_root: PurePath | None
    executable: PurePath | None
    version: str
    usable: bool
    status: str


Probe = Callable[[Candidate], ProbeResult]


def _identity(candidate: Candidate) -> tuple[str, str]:
    identity_platform = (
        f"{candidate.platform}:{candidate.runtime_id}"
        if candidate.platform == "wsl"
        else candidate.platform
    )
    if candidate.source_root is not None:
        root = candidate.source_root
        normalized = root.resolve(strict=False) if isinstance(root, Path) else root
        return (identity_platform, str(normalized).casefold())
    if candidate.executable is not None:
        executable = candidate.executable
        normalized = (
            executable.resolve(strict=False) if isinstance(executable, Path) else executable
        )
        return (identity_platform, str(normalized).casefold())
    return (identity_platform, f"{candidate.runtime_id}:{candidate.home}".casefold())


class RuntimeDiscovery:
    """Probe candidates and collapse aliases for the same backend."""

    def __init__(self, *, probe: Probe):
        self._probe = probe

    def classify(self, candidates: Iterable[Candidate]) -> list[Runtime]:
        groups: dict[tuple[str, str], list[Candidate]] = {}
        for candidate in candidates:
            groups.setdefault(_identity(candidate), []).append(candidate)

        runtimes: list[Runtime] = []
        for group in groups.values():
            primary = group[0]
            probe = self._probe(primary)
            surfaces = tuple(dict.fromkeys(candidate.surface for candidate in group))
            active = any(candidate.active_hint for candidate in group)
            source_root = probe.source_root or primary.source_root
            executable = probe.executable or primary.executable

            if probe.usable and active:
                status = "active"
            elif source_root is None and executable is None:
                status = "legacy/inactive"
            elif probe.usable:
                status = "available"
            else:
                status = "unusable"

            runtimes.append(
                Runtime(
                    runtime_id=primary.runtime_id,
                    surfaces=surfaces,
                    platform=primary.platform,
                    home=primary.home,
                    source_root=source_root,
                    executable=executable,
                    version=probe.version,
                    usable=probe.usable,
                    status=status,
                )
            )
        return runtimes


def select_runtime(runtimes: Iterable[Runtime], requested: str | None = None) -> Runtime:
    """Select one runtime without guessing across multiple usable estates."""

    items = list(runtimes)
    if requested is not None:
        for runtime in items:
            if runtime.runtime_id == requested and runtime.usable:
                return runtime
        raise RuntimeNotFoundError(f"No usable Hermes runtime named {requested!r}")

    active = [runtime for runtime in items if runtime.usable and runtime.status == "active"]
    if len(active) == 1:
        return active[0]
    if len(active) > 1:
        names = ", ".join(runtime.runtime_id for runtime in active)
        raise AmbiguousRuntimeError(f"Multiple active Hermes runtimes found: {names}")

    usable = [runtime for runtime in items if runtime.usable]
    if len(usable) == 1:
        return usable[0]
    if len(usable) > 1:
        names = ", ".join(runtime.runtime_id for runtime in usable)
        raise AmbiguousRuntimeError(f"Multiple usable Hermes runtimes found: {names}")
    raise RuntimeNotFoundError("No usable Hermes runtime found")
