from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cursor_native.discovery import (
    AmbiguousRuntimeError,
    Candidate,
    ProbeResult,
    RuntimeDiscovery,
    RuntimeNotFoundError,
    select_runtime,
)


def _probe(candidate: Candidate) -> ProbeResult:
    return ProbeResult(
        usable=candidate.executable is not None,
        version="0.20.5" if candidate.executable else "",
        source_root=candidate.source_root,
        executable=candidate.executable,
    )


def test_windows_current_legacy_and_wsl_remain_separate(tmp_path: Path) -> None:
    current = tmp_path / "LocalAppData" / "hermes"
    legacy = tmp_path / "User" / ".hermes"
    wsl = Path("/home/stripes/.hermes")

    candidates = [
        Candidate(
            runtime_id="windows-current",
            surface="cli",
            platform="windows",
            home=current,
            source_root=current / "hermes-agent",
            executable=current / "hermes-agent/venv/Scripts/hermes.exe",
            active_hint=True,
        ),
        Candidate(
            runtime_id="windows-legacy",
            surface="legacy",
            platform="windows",
            home=legacy,
            source_root=None,
            executable=None,
            active_hint=False,
        ),
        Candidate(
            runtime_id="wsl:Ubuntu",
            surface="cli",
            platform="wsl",
            home=wsl,
            source_root=wsl / "hermes-agent",
            executable=Path("/home/stripes/.local/bin/hermes"),
            active_hint=False,
        ),
    ]

    runtimes = RuntimeDiscovery(probe=_probe).classify(candidates)

    assert [r.runtime_id for r in runtimes] == [
        "windows-current",
        "windows-legacy",
        "wsl:Ubuntu",
    ]
    assert runtimes[0].status == "active"
    assert runtimes[1].status == "legacy/inactive"
    assert runtimes[2].platform == "wsl"
    assert runtimes[0].home != runtimes[1].home != runtimes[2].home


def test_duplicate_candidates_for_same_backend_are_collapsed(tmp_path: Path) -> None:
    root = tmp_path / "hermes" / "hermes-agent"
    executable = root / "venv/Scripts/hermes.exe"
    candidates = [
        Candidate("windows-current", "cli", "windows", root.parent, root, executable, True),
        Candidate("desktop-local", "desktop", "windows", root.parent, root, executable, True),
    ]

    runtimes = RuntimeDiscovery(probe=_probe).classify(candidates)

    assert len(runtimes) == 1
    assert runtimes[0].runtime_id == "windows-current"
    assert runtimes[0].surfaces == ("cli", "desktop")


def test_same_posix_path_in_different_wsl_distros_never_collapses() -> None:
    candidates = [
        Candidate(
            "wsl:Ubuntu",
            "cli",
            "wsl",
            Path("/home/test/.hermes"),
            Path("/home/test/.hermes/hermes-agent"),
            Path("/home/test/.local/bin/hermes"),
            False,
        ),
        Candidate(
            "wsl:Debian",
            "cli",
            "wsl",
            Path("/home/test/.hermes"),
            Path("/home/test/.hermes/hermes-agent"),
            Path("/home/test/.local/bin/hermes"),
            False,
        ),
    ]

    runtimes = RuntimeDiscovery(probe=_probe).classify(candidates)

    assert [runtime.runtime_id for runtime in runtimes] == ["wsl:Ubuntu", "wsl:Debian"]


def test_select_runtime_uses_only_usable_active_runtime(tmp_path: Path) -> None:
    root = tmp_path / "active"
    runtimes = RuntimeDiscovery(probe=_probe).classify(
        [
            Candidate(
                "windows-current",
                "cli",
                "windows",
                root,
                root / "hermes-agent",
                root / "hermes-agent/venv/Scripts/hermes.exe",
                True,
            ),
            Candidate("windows-legacy", "legacy", "windows", tmp_path / "old", None, None, False),
        ]
    )

    selected = select_runtime(runtimes)

    assert selected.runtime_id == "windows-current"


def test_select_runtime_fails_closed_when_multiple_usable_runtimes_exist(tmp_path: Path) -> None:
    candidates = [
        Candidate(
            "windows-current",
            "cli",
            "windows",
            tmp_path / "win",
            tmp_path / "win/hermes-agent",
            tmp_path / "win/hermes-agent/venv/Scripts/hermes.exe",
            True,
        ),
        Candidate(
            "wsl:Ubuntu",
            "cli",
            "wsl",
            Path("/home/stripes/.hermes"),
            Path("/home/stripes/.hermes/hermes-agent"),
            Path("/home/stripes/.local/bin/hermes"),
            True,
        ),
    ]
    runtimes = RuntimeDiscovery(probe=_probe).classify(candidates)

    with pytest.raises(AmbiguousRuntimeError):
        select_runtime(runtimes)


def test_select_runtime_accepts_explicit_runtime_id(tmp_path: Path) -> None:
    candidates = [
        Candidate(
            "windows-current",
            "cli",
            "windows",
            tmp_path / "win",
            tmp_path / "win/hermes-agent",
            tmp_path / "win/hermes-agent/venv/Scripts/hermes.exe",
            True,
        ),
        Candidate(
            "wsl:Ubuntu",
            "cli",
            "wsl",
            Path("/home/stripes/.hermes"),
            Path("/home/stripes/.hermes/hermes-agent"),
            Path("/home/stripes/.local/bin/hermes"),
            True,
        ),
    ]
    runtimes = RuntimeDiscovery(probe=_probe).classify(candidates)

    selected = select_runtime(runtimes, requested="wsl:Ubuntu")

    assert selected.runtime_id == "wsl:Ubuntu"


def test_select_runtime_rejects_unknown_runtime(tmp_path: Path) -> None:
    runtimes = RuntimeDiscovery(probe=_probe).classify(
        [Candidate("windows-legacy", "legacy", "windows", tmp_path, None, None, False)]
    )

    with pytest.raises(RuntimeNotFoundError):
        select_runtime(runtimes, requested="does-not-exist")


@pytest.mark.parametrize("usable_first", [False, True])
def test_alias_collapse_retains_usable_probe(tmp_path, usable_first):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").touch()
    root = tmp_path / "source"
    broken = Candidate("explicit-home", "explicit", "linux", home, root,
                       root / "venv/bin/hermes", True)
    working = Candidate("path-hermes", "path", "linux", home, None,
                        root / ".venv/bin/hermes")
    candidates = [working, broken] if usable_first else [broken, working]

    def probe(candidate):
        return ProbeResult(candidate == working, "working" if candidate == working else "",
                           root, candidate.executable)

    runtimes = RuntimeDiscovery(probe=probe).classify(candidates)
    assert len(runtimes) == 1
    runtime = select_runtime(runtimes)
    assert runtime.usable and runtime.status == "active"
    assert runtime.version == "working"
    assert runtime.executable == working.executable
    assert runtime.source_root == root
    assert runtime.home == home
    assert set(runtime.surfaces) == {"explicit", "path"}


def test_path_hermes_collapses_with_explicit_home(tmp_path):
    custom_home = tmp_path / "custom-estate"
    custom_home.mkdir()
    checkout = tmp_path / "checkout"
    executable = checkout / "venv" / "bin" / "hermes"
    explicit = Candidate(
        "explicit-home",
        "cli",
        "linux",
        custom_home,
        custom_home / "hermes-agent",
        custom_home / "hermes-agent/venv/bin/hermes",
        True,
    )
    path = Candidate(
        "path-hermes",
        "path",
        "linux",
        custom_home,
        checkout,
        executable,
    )

    def probe(candidate):
        return ProbeResult(
            candidate == path,
            "0.21.1",
            checkout,
            candidate.executable,
        )

    runtime = select_runtime(RuntimeDiscovery(probe=probe).classify([explicit, path]))
    assert runtime.runtime_id == "explicit-home"
    assert runtime.home == custom_home
    assert runtime.executable == executable
    assert runtime.usable


@pytest.mark.parametrize("explicit_first", [True, False])
@pytest.mark.parametrize("other_config", [True, False])
def test_aliases_preserve_unconfigured_explicit_home(tmp_path, explicit_first, other_config):
    home = tmp_path / "requested"
    unrelated = tmp_path / ".hermes"
    home.mkdir()
    unrelated.mkdir()
    if other_config:
        (unrelated / "config.yaml").write_text("unrelated estate")
    source = tmp_path / "shared-checkout"
    explicit = Candidate("explicit-home", "cli", "linux", home, home / "hermes-agent",
                         home / "hermes-agent/venv/bin/hermes", True)
    path = Candidate("path-hermes", "path", "linux", unrelated, source,
                     source / ".venv/bin/hermes")

    def probe(candidate):
        return ProbeResult(candidate == path, "test", source, candidate.executable)

    candidates = [explicit, path] if explicit_first else [path, explicit]
    runtime = select_runtime(RuntimeDiscovery(probe=probe).classify(candidates))
    assert runtime.runtime_id == "explicit-home"
    assert runtime.home == home
    assert runtime.executable == path.executable
    assert not (home / "config.yaml").exists()
    if other_config:
        assert (unrelated / "config.yaml").read_text() == "unrelated estate"
