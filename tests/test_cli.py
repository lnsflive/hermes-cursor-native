from __future__ import annotations

import hermes_cursor_native.cli as cli
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
