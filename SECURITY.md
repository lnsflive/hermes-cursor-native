# Security Policy

## Supported versions

Only the latest tagged alpha is supported. Compatibility is limited to Hermes versions listed in `install-manifest.json`.

## Reporting

Do not open public issues containing credentials, auth files, session dumps, gateway tokens, or private paths. Use GitHub private vulnerability reporting once the public repository enables it.

## Installer guarantees

- Explicit runtime/profile selection for non-interactive writes
- Dry-run plan before mutation
- Clean Git checkout requirement
- Rollback branch before patching
- SHA256 verification of bridge archives
- Tar traversal, symlink, and non-regular-entry rejection
- Loopback/local bridge design
- No credential values in arguments, plans, logs, or reports
- No auth copying between Windows, WSL, users, containers, or remote hosts
- No Desktop shell/app.asar modification for provider installs

## Operator responsibilities

- Review the dry run.
- Close active Hermes backends before source patching.
- Complete OAuth personally.
- Keep the deployment branch and recovery refs.
- Review upstream conflicts before merging updates.
- Never expose bridge or backend ports publicly without authentication and a separate security review.

## Threat model

The primary risks are malicious archives, wrong-runtime selection, credential exposure, source-update conflicts, prompt-originated tool misuse, and Cursor/Hermes protocol drift. The installer fails closed on integrity, compatibility, dirty checkout, ambiguity, or command failures.
