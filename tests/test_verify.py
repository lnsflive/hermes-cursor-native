import json
import subprocess
from pathlib import Path
from subprocess import CompletedProcess

import pytest

import hermes_cursor_native.cli as cli
import hermes_cursor_native.verify as verify
from hermes_cursor_native.discovery import Runtime
from hermes_cursor_native.verify import _safe_auth_status, collect_receipt


@pytest.mark.parametrize(
    ("failure", "note"),
    [
        (OSError("launcher missing"), "auth_status_probe_failed"),
        (subprocess.TimeoutExpired(cmd="hermes", timeout=60), "auth_status_probe_timed_out"),
    ],
)
def test_safe_auth_status_converts_probe_failures(tmp_path, monkeypatch, failure, note):
    hermes = tmp_path / "hermes"
    hermes.touch()
    home = tmp_path / "home"
    home.mkdir()

    def raise_failure(*args, **kwargs):
        raise failure

    monkeypatch.setattr(verify.subprocess, "run", raise_failure)
    status, auth_note = _safe_auth_status(hermes, ["-p", "work"], tmp_path, home)
    assert status == "unknown"
    assert auth_note == note


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (OSError("python missing"), "catalog_probe_failed"),
        (subprocess.TimeoutExpired(cmd="python", timeout=120), "catalog_probe_timed_out"),
    ],
)
def test_receipt_catalog_probe_converts_launch_failures(
    tmp_path, monkeypatch, failure, expected,
):
    home = tmp_path / "home"
    source = tmp_path / "source"
    source.mkdir()
    python = source / "python"
    python.touch()
    runtime = Runtime("test", ("cli",), "linux", home, source, source / "hermes",
                      "test", True, "active")
    python_calls = 0

    def subprocess_run(args, **kwargs):
        if args[-3:] == ["auth", "status", "cursor"]:
            return CompletedProcess(args, 0, "cursor: logged in", "")
        if args[:2] == [str(python), "-c"]:
            nonlocal python_calls
            python_calls += 1
            if python_calls == 1:
                raise failure
            return CompletedProcess(args, 0, '{"ok": true}', "")
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(verify.subprocess, "run", subprocess_run)
    monkeypatch.setattr(verify, "run_contract_checks", lambda *args: {"client_contract": True})
    receipt = collect_receipt(runtime, bridge_path=None)
    assert receipt.model_catalog_error == expected
    assert receipt.chat_probe == "runtime_credentials_ok"


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (OSError("python missing"), "runtime_probe_failed"),
        (subprocess.TimeoutExpired(cmd="python", timeout=60), "runtime_probe_timed_out"),
    ],
)
def test_receipt_runtime_probe_converts_launch_failures(
    tmp_path, monkeypatch, failure, expected,
):
    home = tmp_path / "home"
    source = tmp_path / "source"
    source.mkdir()
    python = source / "python"
    python.touch()
    runtime = Runtime("test", ("cli",), "linux", home, source, source / "hermes",
                      "test", True, "active")
    python_calls = 0

    def subprocess_run(args, **kwargs):
        if args[-3:] == ["auth", "status", "cursor"]:
            return CompletedProcess(args, 0, "cursor: logged in", "")
        if args[:2] == [str(python), "-c"]:
            nonlocal python_calls
            python_calls += 1
            if python_calls == 1:
                return CompletedProcess(args, 0, '{"count": 3}', "")
            raise failure
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(verify.subprocess, "run", subprocess_run)
    monkeypatch.setattr(verify, "run_contract_checks", lambda *args: {"client_contract": True})
    receipt = collect_receipt(runtime, bridge_path=None)
    assert receipt.model_catalog_count == 3
    assert receipt.chat_probe == expected


def test_status_survives_python_probe_failures(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    source = tmp_path / "source"
    source.mkdir()
    python = source / "python"
    python.touch()
    runtime = Runtime("test", ("cli",), "linux", home, source, source / "hermes",
                      "test", True, "active")
    call_count = 0

    def subprocess_run(args, **kwargs):
        nonlocal call_count
        if args[-3:] == ["auth", "status", "cursor"]:
            return CompletedProcess(args, 0, "cursor: logged in", "")
        call_count += 1
        raise OSError("python missing")

    monkeypatch.setattr(verify.subprocess, "run", subprocess_run)
    monkeypatch.setattr(verify, "resolve_hermes_python", lambda _: python)
    monkeypatch.setattr(verify, "run_contract_checks", lambda *args: {"client_contract": True})
    assert cli.main(["status", "--runtime", "test", "--json"],
                    discover=lambda: [runtime]) == 0
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    receipt = json.loads(captured.out)
    assert receipt["model_catalog_error"] == "catalog_probe_failed"
    assert receipt["chat_probe"] == "runtime_probe_failed"


def test_receipt_reports_catalog_fetch_failure(tmp_path, monkeypatch):
    home = tmp_path / "home"
    source = tmp_path / "source"
    source.mkdir()
    python = source / "python"
    python.touch()
    runtime = Runtime("test", ("cli",), "linux", home, source, source / "hermes",
                      "test", True, "active")

    def subprocess_run(args, **kwargs):
        if args[-3:] == ["auth", "status", "cursor"]:
            return CompletedProcess(args, 0, "cursor: logged in", "")
        return CompletedProcess(args, 0, '{"count": null, "error": "catalog_fetch_failed"}', "")

    monkeypatch.setattr(verify.subprocess, "run", subprocess_run)
    monkeypatch.setattr(verify, "resolve_hermes_python", lambda _: python)
    monkeypatch.setattr(verify, "run_contract_checks", lambda *args: {"client_contract": True})
    receipt = collect_receipt(runtime, bridge_path=None)
    assert receipt.model_catalog_count is None
    assert receipt.model_catalog_error == "catalog_fetch_failed"


def test_receipt_contract_probe_converts_launch_failures(tmp_path, monkeypatch):
    import hermes_cursor_native.capabilities as capabilities

    home = tmp_path / "home"
    source = tmp_path / "source"
    source.mkdir()
    python = source / "python"
    python.touch()
    runtime = Runtime("test", ("cli",), "linux", home, source, source / "hermes",
                      "test", True, "active")

    def raise_oserror(*args, **kwargs):
        raise OSError("python missing")

    monkeypatch.setattr(capabilities, "_run_probe", raise_oserror)
    monkeypatch.setattr(verify, "resolve_hermes_python", lambda _: python)
    monkeypatch.setattr(verify, "_safe_auth_status", lambda *args: ("logged out", ""))
    receipt = collect_receipt(runtime, bridge_path=None)
    assert receipt.contract_checks == {
        "plugin_seam": False,
        "provider_client_seam": False,
        "plugin_registered": False,
        "client_contract": False,
    }


def test_status_survives_auth_probe_failure(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    runtime = Runtime("test", ("cli",), "linux", home, None, tmp_path / "hermes",
                      "test", True, "active")

    def raise_oserror(*args, **kwargs):
        raise OSError("launcher missing")

    monkeypatch.setattr(verify.subprocess, "run", raise_oserror)
    monkeypatch.setattr(verify, "resolve_hermes_python", lambda _: None)
    assert cli.main(["status", "--runtime", "test", "--json"],
                    discover=lambda: [runtime]) == 0
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    receipt = json.loads(captured.out)
    assert receipt["auth_status"] == "unknown"
    assert "auth: auth_status_probe_failed" in receipt["notes"]


@pytest.mark.parametrize("profile", ["default", "work"])
@pytest.mark.parametrize("has_python", [False, True])
def test_receipt_probes_selected_home_and_profile(tmp_path, monkeypatch, profile, has_python):
    home = tmp_path / "selected"
    source = tmp_path / "source"
    source.mkdir()
    python = source / "python"
    if has_python:
        python.touch()
    runtime = Runtime("test", ("cli",), "linux", home, source, source / "hermes",
                      "test", True, "active")
    ambient = tmp_path / "unrelated"
    monkeypatch.setenv("HERMES_HOME", str(ambient))
    monkeypatch.setattr(verify, "resolve_hermes_python", lambda _: python if has_python else None)
    probe_home = home if profile == "default" else home / "profiles" / profile
    observed = []

    def subprocess_run(args, **kwargs):
        observed.append(args)
        if args[-3:] == ["auth", "status", "cursor"]:
            assert args[1:3] == ["-p", profile]
            assert kwargs["env"]["HERMES_HOME"] == str(home)
            return CompletedProcess(args, 0, "cursor: logged in", "")
        assert kwargs["env"]["HERMES_HOME"] == str(probe_home)
        assert args[:2] == [str(python), "-c"]
        return CompletedProcess(args, 0, '{"count": 7, "ok": true}', "")

    def contract(interpreter, root, selected):
        assert (interpreter, root, selected) == (python, source, probe_home)
        return {"client_contract": True}

    monkeypatch.setattr(verify.subprocess, "run", subprocess_run)
    monkeypatch.setattr(verify, "run_contract_checks", contract)
    receipt = collect_receipt(runtime, bridge_path=Path("missing"), profile=profile)
    assert receipt.auth_status == "logged in"
    if has_python:
        assert receipt.model_catalog_count == 7
        assert receipt.chat_probe == "runtime_credentials_ok"
        assert len(observed) == 3
    else:
        assert receipt.contract_checks["client_contract"] is False
        assert receipt.model_catalog_error == "python_missing"
        assert receipt.chat_probe == "runtime_probe_unavailable"
        assert len(observed) == 1
    import os
    assert os.environ["HERMES_HOME"] == str(ambient)


@pytest.mark.parametrize("profile", ["default", "work"])
@pytest.mark.parametrize("layout", ["native", "legacy", "missing"])
def test_receipt_detects_plugin_layout(tmp_path, monkeypatch, profile, layout):
    home = tmp_path / "home"
    selected = home if profile == "default" else home / "profiles" / profile
    relative = "plugins/cursor" if layout == "native" else "plugins/model-providers/cursor"
    plugin = selected / relative
    if layout != "missing":
        plugin.mkdir(parents=True)
    # An unrelated profile must not make a missing selected installation healthy.
    (home / "profiles/other/plugins/cursor").mkdir(parents=True)
    runtime = Runtime("test", ("cli",), "linux", home, None, tmp_path / "hermes",
                      "test", True, "active")
    monkeypatch.setattr(verify, "resolve_hermes_python", lambda _: None)
    monkeypatch.setattr(verify, "_safe_auth_status", lambda *args: ("logged out", ""))
    receipt = collect_receipt(runtime, bridge_path=None, profile=profile)
    assert receipt.plugin_installed is (layout != "missing")
    assert receipt.plugin_path == str(plugin)
