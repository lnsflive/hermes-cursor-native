from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from hermes_cursor_native.cli import main
from hermes_cursor_native.discovery import Runtime
from hermes_cursor_native.system_discovery import (
    WslEstate,
    choose_wsl_launcher,
    collect_candidates,
    decode_wsl_distribution_list,
    infer_source_root,
    parse_version_output,
    parse_wsl_probe,
)


def test_infer_source_root_from_windows_venv_executable() -> None:
    executable = Path("C:/Users/test/AppData/Local/hermes/hermes-agent/venv/Scripts/hermes.exe")

    assert infer_source_root(executable) == Path(
        "C:/Users/test/AppData/Local/hermes/hermes-agent"
    )


def test_collect_windows_current_legacy_desktop_override_path_and_wsl() -> None:
    env = {
        "LOCALAPPDATA": "C:/Users/test/AppData/Local",
        "USERPROFILE": "C:/Users/test",
        "HERMES_HOME": "E:/custom-hermes",
        "HERMES_DESKTOP_HERMES_ROOT": "D:/src/hermes-agent",
    }
    existing = {
        Path("C:/Users/test/AppData/Local/hermes"),
        Path("C:/Users/test/.hermes"),
        Path("D:/src/hermes-agent"),
        Path("E:/custom-hermes"),
    }

    candidates = collect_candidates(
        platform_name="windows",
        env=env,
        which_hermes=lambda: Path(
            "C:/Users/test/AppData/Local/hermes/hermes-agent/venv/Scripts/hermes.exe"
        ),
        exists=lambda path: path in existing,
        wsl_estates=lambda: [
            WslEstate(
                distro="Ubuntu",
                home=Path("/home/test/.hermes"),
                executable=Path("/home/test/.local/bin/hermes"),
            )
        ],
    )

    assert [candidate.runtime_id for candidate in candidates] == [
        "desktop-override",
        "explicit-home",
        "windows-current",
        "windows-legacy",
        "path-hermes",
        "wsl:Ubuntu",
    ]
    assert candidates[0].source_root == Path("D:/src/hermes-agent")
    assert candidates[3].source_root is None
    assert candidates[-1].platform == "wsl"


def test_parse_version_output_accepts_install_directory_and_project() -> None:
    windows = """Hermes Agent v0.20.5\nInstall directory: C:\\Hermes\\hermes-agent\n"""
    posix = """Hermes Agent v0.16.0\nProject: /home/test/.hermes/hermes-agent\n"""

    assert parse_version_output(windows) == ("0.20.5", Path("C:/Hermes/hermes-agent"))
    assert parse_version_output(posix) == (
        "0.16.0",
        Path("/home/test/.hermes/hermes-agent"),
    )


def test_parse_version_output_preserves_posix_path_when_requested() -> None:
    output = "Hermes Agent v0.16.0\nProject: /home/stripes/.hermes/hermes-agent\n"

    version, root = parse_version_output(output, path_style="posix")

    assert version == "0.16.0"
    assert root == PurePosixPath("/home/stripes/.hermes/hermes-agent")
    assert str(root) == "/home/stripes/.hermes/hermes-agent"


def test_parse_wsl_probe_rejects_windows_interop_wrapper() -> None:
    assert parse_wsl_probe("/home/stripes\n/mnt/c/Users/test/bin/hermes\n") is None


def test_parse_wsl_probe_accepts_native_wsl_launcher() -> None:
    estate = parse_wsl_probe("/home/stripes\n/home/stripes/.local/bin/hermes\n", "Ubuntu")

    assert estate is not None
    assert estate.home == PurePosixPath("/home/stripes/.hermes")
    assert estate.executable == PurePosixPath("/home/stripes/.local/bin/hermes")


def test_decode_wsl_distribution_list_handles_utf16le() -> None:
    payload = "Ubuntu\r\ndocker-desktop\r\n".encode("utf-16le")

    assert decode_wsl_distribution_list(payload) == ["Ubuntu", "docker-desktop"]


def test_choose_wsl_launcher_prefers_native_standard_locations() -> None:
    home = PurePosixPath("/home/stripes")
    executable = choose_wsl_launcher(
        home,
        is_executable=lambda path: path == PurePosixPath("/home/stripes/.local/bin/hermes"),
    )

    assert executable == PurePosixPath("/home/stripes/.local/bin/hermes")


def test_choose_wsl_launcher_never_uses_windows_interop_path() -> None:
    executable = choose_wsl_launcher(
        PurePosixPath("/home/stripes"),
        is_executable=lambda _path: False,
    )

    assert executable is None


def test_cli_discover_json_is_machine_readable(capsys) -> None:
    runtime = Runtime(
        runtime_id="windows-current",
        surfaces=("cli", "desktop"),
        platform="windows",
        home=Path("C:/Hermes"),
        source_root=Path("C:/Hermes/hermes-agent"),
        executable=Path("C:/Hermes/hermes-agent/venv/Scripts/hermes.exe"),
        version="0.20.5",
        usable=True,
        status="active",
    )

    exit_code = main(["discover", "--json"], discover=lambda: [runtime])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["runtime_id"] == "windows-current"
    assert payload[0]["surfaces"] == ["cli", "desktop"]
    assert payload[0]["source_root"] == str(Path("C:/Hermes/hermes-agent"))
