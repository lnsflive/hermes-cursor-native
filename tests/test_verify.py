from pathlib import Path
from subprocess import CompletedProcess

import pytest

from hermes_cursor_native.discovery import Runtime
from hermes_cursor_native.verify import collect_receipt


@pytest.mark.parametrize("profile", ["default", "work"])
@pytest.mark.parametrize("has_python", [False, True])
def test_receipt_probes_selected_home_and_profile(tmp_path, monkeypatch, profile, has_python):
    import hermes_cursor_native.verify as verify

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
