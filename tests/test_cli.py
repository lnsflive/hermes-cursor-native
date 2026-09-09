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


def test_windows_status_rejects_wsl_before_probing(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    runtime = Runtime("wsl:Ubuntu", ("cli",), "wsl", tmp_path, None,
                      tmp_path / "hermes", "test", True, "active")
    monkeypatch.setattr(cli, "os", SimpleNamespace(name="nt"))

    def unexpected_probe(*args, **kwargs):
        pytest.fail("Windows must not invoke a POSIX runtime")

    monkeypatch.setattr(cli, "collect_receipt", unexpected_probe)
    original_main = cli.main
    monkeypatch.setattr(cli, "main", lambda argv: original_main(argv, discover=lambda: [runtime]))
    assert cli.entrypoint(["status", "--runtime", "wsl:Ubuntu", "--json"]) == 2
    error = capsys.readouterr().err
    assert "Run status inside the selected WSL distribution (wsl:Ubuntu)" in error
    assert "Traceback" not in error
