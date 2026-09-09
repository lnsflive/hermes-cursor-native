from __future__ import annotations

import json

import pytest

import hermes_cursor_native.cli as cli
import hermes_cursor_native.verify as verify
from hermes_cursor_native.discovery import Runtime
from hermes_cursor_native.install_plan import InstallBlockedError


def test_entrypoint_formats_expected_errors_without_traceback(monkeypatch, capsys) -> None:
    def blocked(_argv=None):
        raise InstallBlockedError("checkout is incompatible")

    monkeypatch.setattr(cli, "main", blocked)

    assert cli.entrypoint([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "Error: checkout is incompatible"
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("count", [0, 1, 2])
def test_status_reports_incomplete_bridge(tmp_path, monkeypatch, capsys, count):
    home = tmp_path / "home"
    bridge_root = home / "cursor-sdk-bridge"
    bridge_root.mkdir(parents=True)
    for n in range(count):
        launcher = bridge_root / str(n) / "cursor-sdk-bridge"
        launcher.parent.mkdir()
        launcher.touch()
    runtime = Runtime("test", ("cli",), "linux", home, None, tmp_path / "hermes",
                      "test", True, "active")
    monkeypatch.setattr(verify, "_safe_auth_status", lambda *args: ("logged out", ""))
    assert cli.main(["status", "--runtime", "test", "--json"],
                    discover=lambda: [runtime]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["bridge_installed"] is (count == 1)
    if count != 1:
        assert receipt["bridge_path"] == ""
        assert f"bridge: expected one launcher, found {count}" in receipt["notes"]


@pytest.mark.parametrize("command", ["status", "login"])
def test_windows_commands_reject_wsl_before_probing(tmp_path, monkeypatch, capsys, command):
    from types import SimpleNamespace

    runtime = Runtime("wsl:Ubuntu", ("cli",), "wsl", tmp_path, None,
                      tmp_path / "hermes", "test", True, "active")
    monkeypatch.setattr(cli, "os", SimpleNamespace(name="nt"))

    def unexpected_probe(*args, **kwargs):
        pytest.fail("Windows must not invoke a POSIX runtime")

    monkeypatch.setattr(cli, "collect_receipt", unexpected_probe)
    monkeypatch.setattr(cli, "run_cursor_oauth", unexpected_probe)
    original_main = cli.main
    monkeypatch.setattr(cli, "main", lambda argv: original_main(argv, discover=lambda: [runtime]))
    argv = [command, "--runtime", "wsl:Ubuntu"]
    if command == "status":
        argv.append("--json")
    assert cli.entrypoint(argv) == 2
    error = capsys.readouterr().err
    assert f"Run {command} inside the selected WSL distribution (wsl:Ubuntu)" in error
    assert "Traceback" not in error


@pytest.mark.parametrize("dry_run", [False, True])
def test_install_json_is_one_document(tmp_path, monkeypatch, capsys, dry_run):
    from types import SimpleNamespace

    runtime = Runtime("test", ("cli",), "linux", tmp_path, None,
                      tmp_path / "hermes", "test", True, "active")
    plan = SimpleNamespace(to_json=lambda: json.dumps({"plan": "ready"}))
    calls = []

    def execute(selected_plan, **kwargs):
        calls.append(selected_plan)
        return SimpleNamespace(receipt=SimpleNamespace(
            to_json=lambda: json.dumps({"installed": True}),
        ))

    monkeypatch.setattr(cli, "build_install_plan", lambda **kwargs: plan)
    monkeypatch.setattr(cli, "execute_install_plan", execute)
    args = ["install", "--runtime", "test", "--yes", "--json"]
    if dry_run:
        args.append("--dry-run")
    assert cli.main(args, discover=lambda: [runtime], manifest_loader=lambda _: None) == 0
    assert json.loads(capsys.readouterr().out) == (
        {"plan": "ready"} if dry_run else {"installed": True}
    )
    assert calls == ([] if dry_run else [plan])


@pytest.mark.parametrize("profile_count", [None, 0, 1, 2])
@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_status_prefers_selected_profile_bridge(
    tmp_path, monkeypatch, capsys, profile_count, platform,
):
    home = tmp_path / "home"
    name = "cursor-sdk-bridge.exe" if platform == "windows" else "cursor-sdk-bridge"
    root_launcher = home / "cursor-sdk-bridge" / "bin" / name
    root_launcher.parent.mkdir(parents=True)
    root_launcher.touch()
    other = home / "profiles" / "other" / "cursor-sdk-bridge" / "bin" / name
    other.parent.mkdir(parents=True)
    other.touch()
    profile_root = home / "profiles" / "work" / "cursor-sdk-bridge"
    if profile_count is not None:
        profile_root.mkdir(parents=True)
        for n in range(profile_count):
            launcher = profile_root / str(n) / name
            launcher.parent.mkdir()
            launcher.touch()
    runtime = Runtime("test", ("cli",), platform, home, None, tmp_path / "hermes",
                      "test", True, "active")
    monkeypatch.setattr(verify, "_safe_auth_status", lambda *args: ("logged out", ""))
    assert cli.main(["status", "--runtime", "test", "--profile", "work", "--json"],
                    discover=lambda: [runtime]) == 0
    receipt = json.loads(capsys.readouterr().out)
    expected = root_launcher if profile_count is None else profile_root / "0" / name
    assert receipt["bridge_installed"] is (profile_count in {None, 1})
    assert receipt["bridge_path"] == (str(expected) if profile_count in {None, 1} else "")
    # Default status must continue reporting the estate bridge.
    assert cli.main(["status", "--runtime", "test", "--json"],
                    discover=lambda: [runtime]) == 0
    assert json.loads(capsys.readouterr().out)["bridge_path"] == str(root_launcher)
