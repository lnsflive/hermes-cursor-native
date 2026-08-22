# Installation

> Alpha: only Hermes 0.20.5 at the manifest base commit is accepted for a fresh patch install.

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

Hermes Desktop was not installed on the verification host, so this alpha does not claim a verified macOS Desktop application layout. The installer targets the Hermes backend checkout, not an application bundle.

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
hermes-cursor-native install --dry-run --runtime <id> --profile default
```

Review source root, executable, home, version, branch, artifact, patch series, OAuth, and verification operations.

## Apply

Interactive:

```text
hermes-cursor-native install --runtime <id> --profile default
```

Agent/automation after explicit approval:

```text
hermes-cursor-native install --runtime <id> --profile default --yes
```

## Agent installation

Point an agent to [`INSTALL_AGENT.md`](../INSTALL_AGENT.md). It must show discovery and dry-run output before asking for approval.

## Profiles

The installer configures only the explicitly targeted profile and stores an absolute bridge path in that profile's config. It does not create profiles, bots, or gateway connections. Use `--profile <existing-name>` for an existing Hermes profile; create or connect bots separately with normal Hermes profile and gateway commands.

Cursor SDK OAuth is intentionally scoped to the operating-system user rather than a Hermes profile. Named profiles keep separate Hermes configuration, memory, sessions, and gateway state while sharing that user's Cursor SDK login. OAuth stores are never copied across users, Windows, WSL, macOS, or remote hosts.

## Uninstall and rollback

The alpha records a Git backup branch and profile config backup. Automated `uninstall` is planned before stable release; until then follow [Update survival and rollback](update-survival.md).
