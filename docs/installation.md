# Installation

Install as the OS user who runs Hermes:

```bash
hermes plugins install https://github.com/lnsflive/hermes-cursor-native --enable
hermes model
```

Restart existing Hermes sessions. Select Cursor, sign in if necessary, accept the verified bridge download if missing, and choose an account model. The repository root is a native `kind: model-provider` plugin. There is no Hermes source patch or exact-version gate.

## Optional management CLI

For explicit runtime selection or Hermes without native plugin installation:

```bash
uvx --from git+https://github.com/lnsflive/hermes-cursor-native@main hermes-cursor-native install
```

Or install the management CLI persistently with `uv tool install git+https://github.com/lnsflive/hermes-cursor-native@main`, then:

```bash
hermes-cursor-native discover
hermes-cursor-native install --dry-run
hermes-cursor-native install
```

When several runtimes exist, select one using `--runtime <id>`. Use `--hermes-home <path>` for a separate Hermes home. The installer probes provider/client interfaces, backs up the installed plugin, and preserves default model settings. Use `--yes` for an already-reviewed noninteractive installation. OAuth is optional at install time; `hermes model` offers it afterward.

## Bootstraps

Linux/macOS/WSL:

```bash
curl -fsSL https://raw.githubusercontent.com/lnsflive/hermes-cursor-native/main/install.sh | bash
```

PowerShell:

```powershell
irm https://raw.githubusercontent.com/lnsflive/hermes-cursor-native/main/install.ps1 | iex
```

The bootstraps default to `main`, not the obsolete patch-based release. For reproducible installation, set `HCN_REF` to a reviewed commit/tag. In a shell pipeline, pass that variable to `bash`, for example `curl ... | HCN_REF=<commit> bash`.

## Authentication

Existing `CURSOR_API_KEY`, same-user SDK login, or a same-user CLI API key is reused. CLI access/refresh tokens are not converted or substituted. A CLI browser session without a reusable API key still needs SDK browser login. No credentials are copied between users or hosts.

## Updates and compatibility

Use Hermes's native plugin update command for native installs, or rerun the optional installer from the desired Git ref. Restart Hermes afterward. Use one installation method per home. Historical patch-based installs must not be reapplied; their provenance is retained in Git history.

The bridge version is independently pinned and hash-verified. Hermes compatibility is checked by behavior, not a version allowlist; old releases lacking the provider client interface are unsupported.
