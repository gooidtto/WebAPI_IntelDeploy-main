# Node identity policy

## Rule

The project uses one strict rule:

**Initialize node identity once, then reuse it forever.**

The identity is bound to the Railway Persistent Volume mounted at `/data` (or the path supplied by `RAILWAY_VOLUME_MOUNT_PATH`).

## Identity files

The persistent identity set is:

- `uuid.txt`
- `reality_private_key.txt`
- `reality_public_key.txt`
- `reality_short_ids.json`
- `subscription_token.txt`
- `identity-integrity.json`
- `.node-identity-initialized`

`identity-integrity.json` contains SHA-256 seals for the persistent identity files. It is part of the integrity boundary and is regenerated only when the intentional subscription-token rotation procedure changes the token.

## First deployment

A new, empty Persistent Volume has no identity marker and no identity files. `identity-init.py` creates the complete identity set exactly once.

If the marker is absent but any identity material is already present, startup fails closed rather than accepting or mixing partial identity state.

## Later startup / redeploy / restart

When the marker exists, the initializer does not generate or replace anything. It validates that the complete identity set and integrity seal are valid and then returns `NODE_IDENTITY=REUSED`.

If the marker exists but any identity file is missing, malformed, incomplete, or fails the integrity seal, startup fails closed. The application does **not** generate a replacement identity.

## Intentional subscription-token rotation

The subscription token is normally immutable. An explicit rotation is allowed only through `SUBSCRIPTION_TOKEN_ROTATE_ID` using the strict format `YYYYMMDD-NNN`.

- Empty/unset: no rotation.
- Invalid format or invalid calendar date: fail closed; identity is not modified.
- New valid Rotation ID: rotate only `subscription_token.txt`, update the integrity seal, and record the applied Rotation ID.
- Same Rotation ID: return `ALREADY_APPLIED`; do not rotate again.
- UUID, REALITY keys, and Short IDs are never changed by token rotation.

## Runtime artifacts

`runtime.json`, `state.json`, `manifest.json`, `runtime-manifest.json`, `subscription.txt`, `subscription_url.txt`, and `config.json` are derived runtime artifacts. They may be regenerated from the current Railway deployment environment and must never become the source of node identity.

The subscription URL is derived from the current Railway Public Domain plus the persistent subscription token. Therefore an endpoint change can update the URL without changing the node identity.

## External configuration boundary

`RAILWAY_TOKEN`, `RAILWAY_API_TOKEN`, Node 06 Cloudflare variables, Railway networking, and region/country remain external configuration. The application does not rewrite them to preserve identity.

Railway networking reconciliation is non-destructive: existing Public Domains and TCP Proxies are inspected and reused; missing resources may be created, but existing resources are not destructively deleted.

Deleting or replacing the Persistent Volume intentionally destroys the stored identity and therefore starts a new identity lifecycle.
