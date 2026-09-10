"""Host-specific Hermes runtime collection and probing."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath

from .discovery import Candidate, ProbeResult, Runtime, RuntimeDiscovery


@dataclass(frozen=True)
class WslEstate:
    distro: str
    home: PurePosixPath
    executable: PurePosixPath


Exists = Callable[[Path], bool]
WhichHermes = Callable[[], Path | None]
WslDiscovery = Callable[[], Sequence[WslEstate]]


def infer_source_root(executable: Path) -> Path | None:
    """Infer a source checkout from a standard Hermes venv launcher path."""

    parts = executable.parts
    lowered = [part.casefold() for part in parts]
    try:
        venv_index = lowered.index("venv")
    except ValueError:
        return None
    if venv_index == 0:
        return None
    return Path(*parts[:venv_index])


def _default_executable(source_root: Path, platform_name: str) -> Path:
    if platform_name == "windows":
        return source_root / "venv" / "Scripts" / "hermes.exe"
    return source_root / "venv" / "bin" / "hermes"


def collect_candidates(
    *,
    platform_name: str,
    env: Mapping[str, str],
    which_hermes: WhichHermes,
    exists: Exists,
    wsl_estates: WslDiscovery,
) -> list[Candidate]:
    """Collect candidates without deciding which one the user intended."""

    candidates: list[Candidate] = []

    desktop_root = env.get("HERMES_DESKTOP_HERMES_ROOT", "").strip()
    if desktop_root and exists(Path(desktop_root)):
        root = Path(desktop_root)
        candidates.append(
            Candidate(
                "desktop-override",
                "desktop",
                platform_name,
                Path(env.get("HERMES_HOME", root.parent)),
                root,
                _default_executable(root, platform_name),
                True,
            )
        )

    explicit_home = env.get("HERMES_HOME", "").strip()
    if explicit_home:
        home = Path(explicit_home)
        root = home / "hermes-agent"
        candidates.append(
            Candidate(
                "explicit-home",
                "cli",
                platform_name,
                home,
                root,
                _default_executable(root, platform_name),
                True,
            )
        )

    if platform_name == "windows":
        local_app_data = env.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            home = Path(local_app_data) / "hermes"
            if exists(home):
                root = home / "hermes-agent"
                candidates.append(
                    Candidate(
                        "windows-current",
                        "cli",
                        "windows",
                        home,
                        root,
                        _default_executable(root, "windows"),
                        True,
                    )
                )

        user_profile = env.get("USERPROFILE", "").strip()
        if user_profile:
            legacy = Path(user_profile) / ".hermes"
            if exists(legacy):
                legacy_root = legacy / "hermes-agent"
                has_source = exists(legacy_root)
                candidates.append(
                    Candidate(
                        "windows-legacy",
                        "legacy",
                        "windows",
                        legacy,
                        legacy_root if has_source else None,
                        _default_executable(legacy_root, "windows") if has_source else None,
                        False,
                    )
                )
    elif not explicit_home:
        hermes_home = Path.home() / ".hermes"
        if exists(hermes_home):
            root = hermes_home / "hermes-agent"
            candidates.append(
                Candidate(
                    "posix-current",
                    "cli",
                    platform_name,
                    hermes_home,
                    root,
                    _default_executable(root, platform_name),
                    True,
                )
            )

    path_executable = which_hermes()
    if path_executable is not None:
        source_root = infer_source_root(path_executable)
        if explicit_home:
            home = Path(explicit_home)
        elif exists(Path.home() / ".hermes"):
            home = Path.home() / ".hermes"
        elif source_root is not None:
            home = source_root.parent
        else:
            home = Path.home()
        candidates.append(
            Candidate(
                "path-hermes",
                "cli",
                platform_name,
                home,
                source_root,
                path_executable,
                True,
            )
        )

    for estate in wsl_estates():
        candidates.append(
            Candidate(
                f"wsl:{estate.distro}",
                "cli",
                "wsl",
                estate.home,
                estate.home / "hermes-agent",
                estate.executable,
                False,
            )
        )
    return candidates


_VERSION_RE = re.compile(r"Hermes Agent v([^\s]+)")
_ROOT_RE = re.compile(r"^(?:Install directory|Project):\s*(.+?)\s*$", re.MULTILINE)


def parse_version_output(output: str, *, path_style: str = "native") -> tuple[str, PurePath | None]:
    version_match = _VERSION_RE.search(output)
    root_match = _ROOT_RE.search(output)
    version = version_match.group(1) if version_match else ""
    if not root_match:
        root = None
    elif path_style == "posix":
        root = PurePosixPath(root_match.group(1))
    else:
        root = Path(root_match.group(1).replace("\\", "/"))
    return version, root


def parse_wsl_probe(output: str, distro: str = "") -> WslEstate | None:
    lines = [line.strip() for line in output.splitlines()]
    if len(lines) < 2 or not lines[0] or not lines[1]:
        return None
    executable = PurePosixPath(lines[1])
    if str(executable).startswith("/mnt/"):
        return None
    return WslEstate(
        distro=distro,
        home=PurePosixPath(lines[0]) / ".hermes",
        executable=executable,
    )


def probe_candidate(candidate: Candidate) -> ProbeResult:
    if candidate.executable is None:
        return ProbeResult(usable=False)

    if candidate.platform == "wsl":
        distro = candidate.runtime_id.split(":", 1)[1]
        command = [
            "wsl.exe",
            "-d",
            distro,
            "--",
            str(candidate.executable),
            "--version",
        ]
    else:
        command = [str(candidate.executable), "--version"]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ProbeResult(usable=False, executable=candidate.executable)

    output = f"{completed.stdout}\n{completed.stderr}"
    version, reported_root = parse_version_output(
        output, path_style="posix" if candidate.platform == "wsl" else "native"
    )
    return ProbeResult(
        usable=completed.returncode == 0 and bool(version),
        version=version,
        source_root=reported_root or candidate.source_root,
        executable=candidate.executable,
    )


def decode_wsl_distribution_list(payload: bytes) -> list[str]:
    """Decode the UTF-16LE output emitted by ``wsl.exe -l -q``."""

    if not payload:
        return []
    text = payload.decode("utf-16le", errors="replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def choose_wsl_launcher(
    home: PurePosixPath,
    *,
    is_executable: Callable[[PurePosixPath], bool],
) -> PurePosixPath | None:
    """Choose a native WSL launcher without consulting Windows-interoperability PATH."""

    for candidate in (home / ".local/bin/hermes", home / ".hermes/bin/hermes"):
        if is_executable(candidate):
            return candidate
    return None


def discover_wsl_estates() -> list[WslEstate]:
    if os.name != "nt" or shutil.which("wsl.exe") is None:
        return []
    try:
        listed = subprocess.run(
            ["wsl.exe", "-l", "-q"],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    estates: list[WslEstate] = []
    for distro in decode_wsl_distribution_list(listed.stdout):
        try:
            home_probe = subprocess.run(
                [
                    "wsl.exe",
                    "-d",
                    distro,
                    "--",
                    "sh",
                    "-lc",
                    "printf '%s' \"$HOME\"",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if home_probe.returncode != 0 or not home_probe.stdout.strip():
            continue
        home = PurePosixPath(home_probe.stdout.strip())

        def is_executable(path: PurePosixPath, distro_name: str = distro) -> bool:
            try:
                result = subprocess.run(
                    ["wsl.exe", "-d", distro_name, "--", "test", "-x", str(path)],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return False
            return result.returncode == 0

        executable = choose_wsl_launcher(home, is_executable=is_executable)
        if executable is not None:
            estates.append(WslEstate(distro, home / ".hermes", executable))
    return estates


def discover_system() -> list[Runtime]:
    platform_name = "windows" if os.name == "nt" else sys.platform
    executable = shutil.which("hermes")
    candidates = collect_candidates(
        platform_name=platform_name,
        env=os.environ,
        which_hermes=lambda: Path(executable) if executable else None,
        exists=Path.exists,
        wsl_estates=discover_wsl_estates,
    )
    return RuntimeDiscovery(probe=probe_candidate).classify(candidates)
