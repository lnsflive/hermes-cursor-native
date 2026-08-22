# Troubleshooting

## Provider appears but bridge is missing

Run discovery and inspect the active profile. `cursor_bridge.command` must be an absolute path in that profile's config. Do not rely on PATH across Desktop, gateway, service, and shell processes.

## Unknown provider `cursor`

The active backend does not contain the provider patch or is a long-running process started before installation. Confirm the executable/source root with `discover --json`, then restart that backend.

## Works in CLI but not Desktop

Determine which `hermes serve` backend Desktop resolved. The Electron `Hermes.exe` path is not proof of backend identity. Remote/cloud Desktop connections require installation on the remote backend.

## Windows and WSL disagree

They are independent installations and auth stores. Run discovery, then execute installation inside WSL for `wsl:<distro>` targets.

## Dirty checkout

The installer refuses mutation. Commit, stash, or choose another clean runtime. Never bypass this check with destructive reset/clean commands.

## Existing deployment branch diverges

Reconcile `cursor-provider-deployed` manually. The installer refuses to switch to a stale branch.

## OAuth expired

Run `hermes cursor login` under the operating-system account that owns the active backend. Do not copy another user's auth file.

## Update conflict

Stop and preserve both branches. Rebase or merge the manifest-listed provider patch series onto the new upstream in a disposable worktree, run the full test/smoke matrix, then move the deployed branch.
