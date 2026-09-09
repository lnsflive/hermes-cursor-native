from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

HERMES_SOURCE = Path(os.getenv("HERMES_AGENT_ROOT", str(Path.home() / ".hermes" / "hermes-agent")))
HERMES_PYTHON = HERMES_SOURCE / (
    ".venv/bin/python" if (HERMES_SOURCE / ".venv/bin/python").exists() else "venv/bin/python"
)
PLUGIN_SRC = Path(__file__).resolve().parents[1] / "plugin" / "model-providers" / "cursor"


def _deploy_plugin(home: Path) -> Path:
    dest = home / "plugins" / "model-providers" / "cursor"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(PLUGIN_SRC, dest)
    return dest


def _run_probe(
    script: str,
    *,
    home: Path,
    user_home: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict:
    isolated_home = user_home or (home / "user-home")
    isolated_home.mkdir(parents=True, exist_ok=True)
    env = {
        "HERMES_HOME": str(home),
        "HOME": str(isolated_home),
        "PYTHONPATH": str(HERMES_SOURCE),
    }
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(
        [str(HERMES_PYTHON), "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return json.loads(completed.stdout.strip())


def _sdk_auth_script() -> str:
    expires = int((time.time() + 86400) * 1000)
    return f"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["PYTHONPATH"])
home = Path(os.environ["HOME"])
auth = home / ".cursor" / "sdk" / "auth.json"
auth.parent.mkdir(parents=True, exist_ok=True)
auth.write_text(json.dumps({{
    "version": 1,
    "backendUrl": "https://api2.cursor.sh",
    "apiKey": "probe-sdk-key-not-real",
    "apiKeyExpiresAtMs": {expires},
}}), encoding="utf-8")
auth.chmod(0o600)
"""


REGRESSION_PROBE = """
import json
import os
import sys

sys.path.insert(0, os.environ["PYTHONPATH"])

from hermes_cli.auth import get_auth_status
from hermes_cli.inventory import build_models_payload, load_picker_context
from hermes_cli.main_provider_setup import _build_provider_picker_rows
from providers import get_provider_profile

status = get_auth_status("cursor")
ctx = load_picker_context()
chat_payload = build_models_payload(
    ctx, for_picker=True, probe_custom_providers=False, max_models=100
)
web_payload = build_models_payload(
    ctx, for_picker=False, probe_custom_providers=False, max_models=100
)
chat_rows = [r for r in chat_payload["providers"] if r.get("slug") == "cursor"]
web_rows = [r for r in web_payload["providers"] if r.get("slug") == "cursor"]
report = {
    "provider_registered": get_provider_profile("cursor") is not None,
    "setup_picker_visible": any(
        row[0] == "cursor" for row in _build_provider_picker_rows({}, "", {}, {})[0]
    ),
    "authenticated": bool(status.get("logged_in")),
    "chat_picker_visible": bool(chat_rows),
    "chat_picker_model_count": len(chat_rows[0].get("models", [])) if chat_rows else 0,
    "web_inventory_visible": bool(web_rows),
    "web_inventory_model_count": len(web_rows[0].get("models", [])) if web_rows else 0,
}
print(json.dumps(report))
"""


@pytest.mark.skipif(not HERMES_PYTHON.is_file(), reason="stock Hermes python not present")
@pytest.mark.parametrize(
    "first_import",
    [
        "",
        "import hermes_cli.main\n",
        "import hermes_cli.models\n",
        "import providers; providers.list_providers()\n",
    ],
)
def test_regression_probe_authenticated_inventory_via_normal_imports(first_import) -> None:
    with tempfile.TemporaryDirectory(prefix="cursor-ui-regression-") as tmp:
        home = Path(tmp)
        _deploy_plugin(home)
        script = _sdk_auth_script() + first_import + REGRESSION_PROBE
        payload = _run_probe(script, home=home)
        assert payload["provider_registered"] is True
        assert payload["setup_picker_visible"] is True
        assert payload["authenticated"] is True
        assert payload["chat_picker_visible"] is True
        assert payload["web_inventory_visible"] is True
        assert payload["chat_picker_model_count"] >= 1
        assert payload["web_inventory_model_count"] >= 1


@pytest.mark.skipif(not HERMES_PYTHON.is_file(), reason="stock Hermes python not present")
def test_regression_probe_logged_out_omits_chat_inventory() -> None:
    with tempfile.TemporaryDirectory(prefix="cursor-ui-loggedout-") as tmp:
        home = Path(tmp)
        _deploy_plugin(home)
        payload = _run_probe(REGRESSION_PROBE, home=home)
        assert payload["provider_registered"] is True
        assert payload["setup_picker_visible"] is True
        assert payload["authenticated"] is False
        assert payload["chat_picker_visible"] is False
        assert payload["web_inventory_visible"] is False


@pytest.mark.skipif(not HERMES_PYTHON.is_file(), reason="stock Hermes python not present")
def test_cursor_dispatches_to_oauth_flow_via_api_key_wrapper() -> None:
    with tempfile.TemporaryDirectory(prefix="cursor-ui-flow-") as tmp:
        home = Path(tmp)
        _deploy_plugin(home)
        payload = _run_probe(
            """
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.environ["PYTHONPATH"])

from hermes_cli.inventory import load_picker_context
import hermes_cli.model_setup_flows as flows_mod

load_picker_context()
wrapper = flows_mod._model_flow_api_key_provider
calls = []

def fake_cursor_flow(config, current_model="", args=None):
    calls.append("cursor")

with patch("_hermes_user_provider_cursor.setup_flow.model_flow_cursor", fake_cursor_flow):
    wrapper({}, "cursor", "")

print(json.dumps({
    "cursor_calls": len(calls),
    "flow_wrapped": bool(getattr(wrapper, "_cursor_flow_wrapper", False)),
}))
""",
            home=home,
        )
        assert payload["flow_wrapped"] is True
        assert payload["cursor_calls"] == 1


@pytest.mark.skipif(not HERMES_PYTHON.is_file(), reason="stock Hermes python not present")
def test_picker_shim_via_auth_inventory_models_import_order() -> None:
    with tempfile.TemporaryDirectory(prefix="cursor-ui-models-") as tmp:
        home = Path(tmp)
        _deploy_plugin(home)
        script = (
            _sdk_auth_script()
            + """
from hermes_cli.auth import get_auth_status
from hermes_cli.inventory import load_picker_context
from hermes_cli.models import provider_model_ids
import hermes_cli.model_switch_providers as picker_mod

get_auth_status("cursor")
load_picker_context()
print(json.dumps({
    "sdk_creds": picker_mod._auth_store_has_provider("cursor"),
    "model_ids": provider_model_ids("cursor"),
}))
"""
        )
        payload = _run_probe(script, home=home)
        assert payload["sdk_creds"] is True
        assert payload["model_ids"]


@pytest.mark.skipif(not HERMES_PYTHON.is_file(), reason="stock Hermes python not present")
def test_logged_out_setup_reaches_browser_login_without_key_prompt() -> None:
    with tempfile.TemporaryDirectory(prefix="cursor-ui-login-") as tmp:
        home = Path(tmp)
        _deploy_plugin(home)
        payload = _run_probe(
            """
import contextlib, io, json
from unittest.mock import patch
import hermes_cli.main as main
from providers import get_provider_profile
get_provider_profile("cursor")
with contextlib.redirect_stdout(io.StringIO()):
    target = "_hermes_user_provider_cursor.cursor_sdk_auth.login"
    with patch(target, side_effect=KeyboardInterrupt) as login:
        try:
            main._model_flow_api_key_provider({}, "cursor", "")
        except KeyboardInterrupt:
            pass
print(json.dumps({"browser_login_called": login.call_count == 1}))
""",
            home=home,
        )
        assert payload["browser_login_called"]


@pytest.mark.skipif(not HERMES_PYTHON.is_file(), reason="stock Hermes python not present")
def test_authenticated_cursor_respects_excluded_provider() -> None:
    with tempfile.TemporaryDirectory(prefix="cursor-ui-excluded-") as tmp:
        home = Path(tmp)
        _deploy_plugin(home)
        payload = _run_probe(
            _sdk_auth_script()
            + """
from dataclasses import replace
from hermes_cli.inventory import load_picker_context, build_models_payload
ctx = replace(load_picker_context(), excluded_providers=["cursor"])
rows = build_models_payload(ctx, for_picker=True, probe_custom_providers=False)['providers']
print(json.dumps({"cursor_present": any(r.get("slug") == "cursor" for r in rows)}))
""",
            home=home,
        )
        assert not payload["cursor_present"]
