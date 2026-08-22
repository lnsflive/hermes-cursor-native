# Update Survival and Rollback

## Alpha patch mode

The installer creates:

- backup branch `backup/hermes-cursor-native-<timestamp>`
- maintained branch `cursor-provider-deployed`
- profile config backup under `<HERMES_HOME>/cursor-native/backups/<timestamp>/config.yaml`

It configures:

```yaml
updates:
  parked_branch_strategy: update_in_place
```

## Updating Hermes

Run normal `hermes update` only while the checkout is on `cursor-provider-deployed`. Upstream is merged into the maintained branch. Conflicts must stop for manual reconciliation.

Never use `hermes update --switch-branch` unless intentionally disabling the provider.

After an update, verify:

```text
hermes --version
hermes chat --provider cursor -m composer-2.5 -q "Reply exactly UPDATE_OK" -Q
hermes chat --provider cursor -m grok-4.6 -q "Reply exactly GROK_UPDATE_OK" -Q
```

## Rollback

1. Stop Desktop-managed backends and gateways using the target checkout.
2. Switch to the recorded backup branch.
3. Restore the recorded config backup.
4. Restart the backend/gateway.
5. Verify the previous provider still works.

Do not reset or clean an unknown dirty checkout. Preserve the failed deployment branch for diagnostics.

## Compatibility updates

Each Hermes base needs a newly tested patch series. Never reuse a patch merely because the version string is unchanged; the manifest base commit is enforced.
