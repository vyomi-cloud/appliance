# Mesh session tokens v2 (Ed25519): closing finding F2

Status: Mesh and relay side on `v4/mesh-session-ed25519` (accept v2 with the pinned `portal-2026-11` key, still accept v1).
Portal side on `portal/mesh-session-ed25519` (mints v2 behind a switch, off by default). F2 stays open until phase 3 below. Context: `MCP-GUARDRAILS-INCIDENT-DESIGN.md` §4.

## 1. Problem

v1 tokens are HMAC-signed. The portal signs each one with a per-session key, `hex(HMAC(master, "session:<id>"))`, and sends
that key to the Codespace (`GET /api/mesh/session/token` answers `{token, key, session_end}`; `boot-mesh.sh` puts both in the
simulator's environment). Anyone with the key can sign their own tokens. A Codespace owner can read it (`docker inspect`, or
the same portal call) and mint a Max token with any `session_end` for their own Mesh. Both the Mesh (`core/mesh_session.py`)
and the relay (`wasm/relay/mesh-session.mjs`, which re-derives the per-session key from the master) accept it.

## 2. v2 format

```
v2.<b64url(payload-json)>.<b64url(Ed25519 signature over the ASCII bytes "v2." + b64url(payload-json))>
```
- b64url: RFC 4648 URL-safe alphabet, no padding.
- payload: the v1 claims plus `kid` (the portal also adds `model_window_s`; verifiers ignore claims they do not use): `{"aud":"vyomi-mesh-session","kid":..,"sub":..,"tier":..,"primary_cloud":..,"session_id":..,"iat":..,"session_end":..}`,
  plus `role` / `model` for runner tokens. Compact JSON (`separators=(",", ":")`), keys sorted. Verifiers do not depend on the
  key order (they verify the signature over the exact bytes sent), but sorted keys make tokens reproducible.
- `kid` selects the public key. It is inside the signed payload.
- Claim checks are unchanged: `aud`, `iat` (30 s skew), `session_end` (410 when passed), tier Pro/Max/Enterprise, `session_id`
  required at the relay, runner-role tokens never drive a Mesh.

## 3. Where the keys live

| Key | Where | Who can read it |
|---|---|---|
| Private (32-byte seed) | Portal secret `MESH_SESSION_SIGNING_KEY` (+ `MESH_SESSION_SIGNING_KID`) | Portal only |
| Public | `TRUSTED_KEYS` constant in `core/mesh_session.py` AND `wasm/relay/mesh-session.mjs` (`tests/test_mesh_session_v2.py` fails if they differ) | Everyone; that is fine |

The public keys and `V1_ACCEPTED` are code constants on purpose. Anything the Mesh reads from its environment or a file is
under the Codespace owner's control: an env-supplied public key or an env switch for v1 would reopen F2. A test
(`test_the_environment_cannot_add_a_trusted_key`) pins this.

Generate a key: `python3 scripts/mesh-session-keygen.py [kid]`. It prints the private seed for the portal secret and the
public-key line for both files, and writes nothing to disk.

Residual risk, stated plainly: a Codespace owner can still run a modified simulator image with their own key pinned. That
is MESH-SOFTWARE-PROTECTION layers 4 (compiled image) and 6 (portal integrity check), not this change.

## 4. Portal changes (`app/mesh_session.py`, branch `portal/mesh-session-ed25519`)

| Env (portal, DigitalOcean, encrypted) | Value |
|---|---|
| `MESH_SESSION_SIGNING_KEY` | the private seed from `scripts/mesh-session-keygen.py` |
| `MESH_SESSION_SIGNING_KID` | `portal-2026-11` (must equal the pinned kid) |
| `MESH_SESSION_TOKEN_VERSION` | `v1` (default) until the pinned Mesh image and relay are live, then `v2` |

- With all three set and valid, `_sign_token` mints v2 (session and runner tokens); anything else mints v1 and logs an error once.
  Setting the key without the switch changes nothing, so the secret can go in with any deploy.
- `GET /api/mesh/session/token` returns `key` only for a v1 token.
- `_runner_auth` accepts the portal's own v2 tokens (and v1 while v1 is minted).
- `MESH_SESSION_KEY` (the HMAC master) stays until phase 4: the relay hubs verify v1 with it.

## 5. Rollout

| Phase | Change | Who | F2 |
|---|---|---|---|
| 1 | Merge appliance #700 (accepts v2, pins `portal-2026-11`); release a Mesh image; redeploy the hosted relay with this `mesh-session.mjs` | owner | open |
| 2 | Merge the portal PR; set `MESH_SESSION_SIGNING_KEY` + `MESH_SESSION_SIGNING_KID`; once phase 1 is live everywhere, set `MESH_SESSION_TOKEN_VERSION=v2` | owner | open (v1 still accepted) |
| 3 | After the longest session lifetime (8 h cap) of v2-only minting: `V1_ACCEPTED = False` in both files; release the Mesh image; redeploy the relay | PR + owner | **closed** for Meshes on that image |
| 4 | Remove the v1 code paths, the portal's v1 branch and `MESH_SESSION_KEY` | PR | closed |

Order matters: turning on `MESH_SESSION_TOKEN_VERSION=v2` before a Mesh image pinning the key is live makes every new session fail
(`MeshSessionUnknownKey`). Rolling back is the same switch set back to `v1`.

Phase 3 only protects Meshes running the new image. `docker-compose.mesh.yml` pins `vyomi/appliance:v4-preview`
(`pull_policy: always`), so new Codespaces pick it up on their next boot.

The guardrail gate (`tools/guardrails/run.sh`) shows F2 as GAP until phase 3, and turns it PASS by itself after that.

## 6. Test vector (test only: never pin this key)

```
seed (base64url)  AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8      (bytes 0x00..0x1f)
public key        A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg
kid               test-vector
claims            sub=acct-42 tier=pro primary_cloud=aws session_id=sess-42 iat=1799990000 session_end=1800000000
token             v2.eyJhdWQiOiJ2eW9taS1tZXNoLXNlc3Npb24iLCJpYXQiOjE3OTk5OTAwMDAsImtpZCI6InRlc3QtdmVjdG9yIiwicHJpbWFyeV9jbG91ZCI6ImF3cyIsInNlc3Npb25fZW5kIjoxODAwMDAwMDAwLCJzZXNzaW9uX2lkIjoic2Vzcy00MiIsInN1YiI6ImFjY3QtNDIiLCJ0aWVyIjoicHJvIn0.sRO_8_vBwgTtn-uO0eiql8uVuJkxVy6o40Fx_w0ywQPofrb2h1L-667sJiji6eNdcELd0l3byBJOVgEKynxdAQ
```
Ed25519 is deterministic, so a correct implementation produces exactly this token from these inputs.
