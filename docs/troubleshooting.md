# Troubleshooting

## Provider appears but bridge is missing

Run `hermes-cursor-native status --json`. `bridge_installed` must be true and `cursor_bridge.command` in the active profile must be an absolute path. Re-run `install` if the bridge tree was removed.

## Unknown provider `cursor`

The active backend was started before plugin install or `$HERMES_HOME` does not contain `plugins/model-providers/cursor/`. Confirm with `discover --json` and `status --json`, then restart long-running gateways/backends.

## Capability probes fail at install time

| Symptom | Likely cause |
|---------|----------------|
| `plugin_seam` false | Hermes version too old; missing `ProviderProfile.create_client` |
| `provider_client_seam` false | Stock Hermes does not route provider clients |
| `plugin_registered` false | Plugin files missing or unreadable under `$HERMES_HOME` |
| `client_contract` false | Plugin load error; shared venv unreadable for non-root user |

For shared `/usr/local/lib/hermes-agent` installs, non-root users need traverse/read on `venv/lib/python3.11/site-packages` (diagnose with `namei -l` on a package `__init__.py`).

## Works in CLI but not Desktop

Determine which `hermes serve` backend Desktop resolved. Remote/cloud Desktop connections require installation on the remote backend's `$HERMES_HOME`.

## Windows and WSL disagree

They are independent installations and auth stores. Run discovery, then execute installation inside WSL for `wsl:<distro>` targets.

## OAuth expired or logged out

Run `hermes-cursor-native login --runtime <id> --hermes-home <path>` under the operating-system account that owns the estate. Do not copy another user's auth file. Do not start duplicate login if the user already has a browser flow open.

## Offline probes pass but chat fails

Offline `contract_checks` do not prove live inference. After OAuth, verify:

```text
hermes auth status cursor
hermes-cursor-native status --json
hermes chat --provider cursor -m "ping"
```

## Install blocked: runtime not ready

`install` refuses when capability probes fail. Fix the underlying seam (Hermes version, plugin path, venv permissions) before retrying. Do not bypass with core patches unless maintaining a legacy deployment.
