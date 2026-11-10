# vyomi-tunnel credentials - contract (portal <-> tunnel)

Status: 2026-11-10. Tunnel side built on `v4/mesh-ssh-transport`; portal side built on portal branch `portal/tunnel-credentials` (`app/tunnel_credentials.py`, page `/account/tunnel-credentials`), verified locally against the real CLI; NOT merged to `v4-nano-portal`, NOT deployed to vyomi.cloud.
Model: the AWS CLI. No `login` command. The user creates an access key in the console and saves it as `~/.vyomi/credentials`.

## 1. The user's side

**Where to download the access key and secret:** `https://vyomi.cloud/account/tunnel-credentials` (console: avatar menu > **Tunnel credentials**). The tunnel prints this URL whenever credentials are missing or rejected. *Built in the portal branch above; live only after it is merged and deployed.*

The page: create access key (secret shown once, "Download credentials" button), list, rotate, revoke.

`~/.vyomi/credentials` (mode 600), INI like `~/.aws/credentials`:

```
[default]
vyomi_access_key_id     = VYKA1B2C3D4E5F6G7H8I
vyomi_secret_access_key = <40+ chars>
portal                  = https://vyomi.cloud      ; optional
github_token            = ghp_...                  ; optional, Pro/Max fallback if the portal does not vend one
```

Overrides: `VYOMI_ACCESS_KEY_ID`, `VYOMI_SECRET_ACCESS_KEY`, `VYOMI_PORTAL_URL`, `VYOMI_PROFILE` (default `default`), `VYOMI_CREDENTIALS_FILE`.
**Every command needs a key, Nano included** (decision 2026-11-10: no details are exposed over an unauthorised transport). A Free key works for Nano only; Mesh needs Pro/Max. The relay (`vyomi-tunnel` with no arguments) refuses to start without a valid key.

## 2. Session exchange

`POST {portal}/api/tunnel/session`, body `{"client":"vyomi-tunnel/<version>"}`.

Headers (the secret never travels):

| Header | Value |
|---|---|
| `X-Vyomi-Key` | access key id |
| `X-Vyomi-Date` | ISO-8601 UTC, e.g. `2026-11-10T07:30:00Z` (server rejects skew > 5 min) |
| `X-Vyomi-Signature` | hex `HMAC-SHA256(secret, "POST\n/api/tunnel/session\n<date>\n<sha256hex(body)>")` |

200 response:

```json
{ "session": {
    "expires_at": 1762760000,            // epoch s; client refreshes when < 120 s left
    "tier": "pro",                       // free | lite | pro | max | enterprise
    "allowed": true,                     // server's verdict: plan allows MESH (a 200 with false = valid key, Nano only)
    "session_end": 1762770000,           // epoch s the Mesh session ends, or null
    "mesh": { "codespace": "vyomi-mesh-abc", "state": "Available" },   // or null when Mesh is not started
    "github": { "token": "gho_...", "expires_at": 1762763600 }         // short-lived, codespace scope; or null
} }
```

Errors (JSON `{"error":{"code","message"}}`):

| HTTP | code | Client message |
|---|---|---|
| 401 | InvalidAccessKey / SignatureMismatch | credentials are wrong; create a new key |
| 401 | RequestTimeSkew | fix your system clock |
| 403 | KeyRevoked | this key was revoked |
| 403 | PlanNotAllowed | Mesh needs Pro or Max |
| 409 | NoMeshSession | start Mesh in the console |
| 429 | Throttled | retry later |

## 3. Client behaviour

- Session cached in memory; refreshed when under 120 s remain. A refresh failure with 401/403 stops the tunnel.
- Every command first needs a 200 (valid key). Mesh commands additionally refuse unless `allowed` is true.
- Not yet authenticated: the relay's loopback HTTP endpoints (`/health`, `/vm`, `/db`, the SDK endpoint) while it runs; a per-request relay token needs a way to hand it to the Nano tab (open item).
- Open streams and forwards are closed at `session_end`.
- `github.token` (else `github_token` from the file) is passed to `gh` as `GH_TOKEN`; the user never runs `gh auth`.
- The Codespace is `session.mesh.codespace`; `--codespace`/`VYOMI_MESH_CODESPACE` override; otherwise discovery on the GitHub account.
- First Mesh command also writes the `*.vyomi` ssh block (`~/.vyomi/ssh_config` + one Include in `~/.ssh/config`).

## 4. Portal work (not built)

Key store (id, hashed-secret-or-HMAC-key, user, created, last_used, revoked); avatar page; `/api/tunnel/session`; the GitHub token vending
from the user's existing GitHub connection (prefer a GitHub App user-to-server token); stop the Codespace at `session_end`.
Server-side enforcement stays authoritative: the client check is a gate, not security.
