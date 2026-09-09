# Installation

> **Plugin-only:** installs into `$HERMES_HOME` on stock Hermes. No core patches, no version-pinned base commit, no Git branch mutation. Run `discover` and `install --dry-run` before applying.

## Requirements

- Stock Hermes Agent with a runnable executable and source checkout (tested on 0.21.1).
- Behavioral capability probes must pass for the selected runtime (see [Architecture](architecture.md)).
- User approval for the exact runtime, profile, and `$HERMES_HOME` (use `--hermes-home` for non-default estates).

## Windows

```powershell
irm https://raw.githubusercontent.com/lnsflive/hermes-cursor-native/v0.1.0-alpha.1/install.ps1 | iex
```

The bootstrap installs `hermes-cursor-native`, discovers runtimes, and starts a guided install. Browser OAuth and ambiguous runtime selection require interaction.

## macOS / Linux / WSL

```bash
curl -fsSL https://raw.githubusercontent.com/lnsflive/hermes-cursor-native/v0.1.0-alpha.1/install.sh | bash
```

Run the POSIX command inside WSL. Do not target a WSL UNC directory with the Windows installer.

Verified native macOS CLI defaults are:

```text
~/.local/bin/hermes -> ~/.hermes/hermes-agent/venv/bin/hermes
~/.hermes/hermes-agent
~/.hermes/config.yaml
~/.hermes/.env
```

The POSIX bootstrap prefers `uv`. If macOS only exposes the system Python 3.9, it can use Python 3.11+ from an existing git-installed Hermes runtime and creates a separate management virtual environment under `~/.local/share/hermes-cursor-native/venv`; it does not install this package into Hermes's own venv.

## Alternate pinned release

```powershell
$env:HCN_REF = "v0.1.0-alpha.1"
irm https://raw.githubusercontent.com/lnsflive/hermes-cursor-native/v0.1.0-alpha.1/install.ps1 | iex
```

```bash
HCN_REF=v0.1.0-alpha.1 curl -fsSL https://raw.githubusercontent.com/lnsflive/hermes-cursor-native/v0.1.0-alpha.1/install.sh | bash
```

## Discover and dry-run

```text
hermes-cursor-native discover
hermes-cursor-native discover --json
hermes-cursor-native install --dry-run --runtime <id> --profile default
```

Review source root, executable, home, version, bridge artifact, capability probe results, OAuth step, and verification operations. For additional user homes on a shared host:

```text
hermes-cursor-native install --dry-run --runtime path-hermes \
  --hermes-home /home/<user>/.hermes --profile default
```

Run the install command **as the intended OS user** so plugin and bridge ownership match the estate.

## Apply

Interactive:

```text
hermes-cursor-native install --runtime <id> --profile default
```

Agent/automation after explicit approval:

```text
hermes-cursor-native install --runtime <id> --profile default --yes
```

OAuth is skipped by default. After install, the user completes browser login:

```text
hermes-cursor-native login --runtime <id> --hermes-home <path>
```

Or pass `--oauth` during install to launch login immediately.

## Agent installation

Point an agent to [`INSTALL_AGENT.md`](../INSTALL_AGENT.md). It must show discovery and dry-run output before asking for approval.

## Profiles

The installer configures only the explicitly targeted profile and stores an absolute bridge path in that profile's config. It does not create profiles, bots, or gateway connections.

Cursor SDK OAuth is scoped to the operating-system user. Named profiles keep separate Hermes configuration while sharing that user's Cursor SDK login. OAuth stores are never copied across users, Windows, WSL, macOS, or remote hosts.

## Post-install verification

```text
hermes-cursor-native status --runtime <id> --hermes-home <path> --json
```

Offline contract checks pass at install time. **Live** auth, model catalog, chat, and Hermes-owned tool execution require completed OAuth — see [Architecture](architecture.md#end-to-end-verification-post-oauth-required).

## Uninstall and rollback

Config backups are stored under `<HERMES_HOME>/cursor-native/backups/<timestamp>/`. Remove the plugin directory and bridge tree to uninstall. Automated `uninstall` is planned before stable release.
