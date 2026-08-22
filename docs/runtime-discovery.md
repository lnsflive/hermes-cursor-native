# Runtime Discovery

Hermes Cursor Native installs into the backend that owns provider discovery—not the Desktop Electron shell.

## Candidate estates

- Native Windows current: `%LOCALAPPDATA%\hermes`
- Native Windows legacy: `%USERPROFILE%\.hermes`
- Explicit `HERMES_HOME`
- `HERMES_DESKTOP_HERMES_ROOT`
- Hermes command on PATH
- Source checkouts selected by explicit override or the active PATH launcher
- WSL distributions: `/home/<user>/.hermes`
- Named profiles under each estate
- Remote/cloud/SSH Desktop backends (planned; not discovered by the alpha)

## Classification

A candidate is usable only when its own executable returns a valid `hermes --version`. Existing data without a runnable source/executable is `legacy/inactive`, never an install target.

Candidates resolving to the same source checkout collapse into one backend with multiple surfaces. Separate Windows/WSL estates never collapse.

## Selection

- One active usable runtime: may be preselected for an interactive user.
- Multiple usable runtimes: display all and require runtime id.
- `--yes`: always requires explicit `--runtime`.
- Remote Desktop: the alpha does not discover registry entries; run installation on the backend host, not the local shell.

## WSL

WSL discovery decodes `wsl.exe -l -q` as UTF-16LE and probes native Linux launchers directly. Windows-interoperability paths under `/mnt` are rejected.

## macOS CLI layout

Verified git-installer defaults on Apple Silicon are `~/.hermes/hermes-agent` for source and `~/.local/bin/hermes` as a symlink to `~/.hermes/hermes-agent/venv/bin/hermes`. Configuration remains under `~/.hermes/`. macOS Desktop bundle/backend discovery remains unverified until Hermes Desktop is installed on a test host.

## Machine-readable output

```text
hermes-cursor-native discover --json
```

Agents and automation must consume this output rather than infer paths from screenshots, process titles, or `Hermes.exe` location.
