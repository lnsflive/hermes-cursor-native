# Update Survival and Rollback

## Plugin-only installs

The installer writes under `$HERMES_HOME` only:

- `plugins/model-providers/cursor/`
- `cursor-sdk-bridge/`
- `cursor-native/backups/<timestamp>/` (config and prior bridge snapshots)

It does **not** modify the Hermes source checkout, Git branches, or core packages.

## Updating this repository

Re-run `install` after pulling a newer `hermes-cursor-native` to refresh the plugin and bridge. Re-run capability probes and, after OAuth, live verification.

## Updating Hermes

Run normal `hermes update` on the shared or per-estate checkout. The plugin under `$HERMES_HOME` survives stock updates. After a major Hermes upgrade:

```text
hermes --version
hermes-cursor-native status --runtime <id> --hermes-home <path> --json
```

If capability probes fail on the new version, stop and reconcile before production use.

After OAuth, live smoke:

```text
hermes auth status cursor
hermes chat --provider cursor -m "Reply exactly UPDATE_OK" --max-tokens 20
```

## Rollback

1. Stop gateways/backends using the target `$HERMES_HOME`.
2. Restore config from `<HERMES_HOME>/cursor-native/backups/<timestamp>/config.yaml`.
3. Remove or restore `plugins/model-providers/cursor/` and `cursor-sdk-bridge/` from the same backup if needed.
4. Restart the backend/gateway.
5. Verify the previous provider configuration still works.

## Historical patch mode

Legacy patch-based deployments used `cursor-provider-deployed` branches and `git am`. That path is **not** supported by the current installer. See `patches/hermes/` for provenance only.
