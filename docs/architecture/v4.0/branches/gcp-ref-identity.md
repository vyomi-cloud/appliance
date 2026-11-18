# v4/gcp-ref-identity

Owner: GCP reference-architecture lane 5 - Started: 2026-11-18 - Base: origin/v4-on-main (a54fc442f) - Status: ready for review

## Purpose
Reference component 1 (Access) on GCP: Identity Platform sign-in with verifiable Google-style ID tokens, and API Gateway that accepts real OpenAPI YAML and validates those tokens. Evidence: `REF-ARCH-PROBE-GCP.md` (branch v4/ref-arch-probe-gcp), probe_01.

## Changes
- `core/gcp_identityplatform_core.py` (new): identitytoolkit `accounts:signUp / signInWithPassword / lookup / update / delete / sendOobCode`, Admin `projects/{p}/accounts[:update|:lookup|:delete|:batchGet]` (create user, `customAttributes` custom claims), securetoken refresh (`POST /v1/token`), the x509 / JWKS / OIDC-discovery documents. Also served under `/identitytoolkit.googleapis.com/...` so the Firebase Admin SDK works with `FIREBASE_AUTH_EMULATOR_HOST`. Routed in `core/aws_wire_router.py` (`gcp-identityplatform`); state in `gcp_mon.ext["idp"]` (persisted with the monitoring store). Registered in `wasm/build_cores.py`, `relay-shared-worker.js`, `nano-endpoint.html`.
- `core/gcp_apigateway_core.py`: `parse_openapi` uses PyYAML (block + flow + JSON, parse errors report the line; the old subset parser is only a fallback when PyYAML is absent). LRO responses carry typed `Api` / `ApiConfig` / `Gateway` Any types (the real `google-cloud-api-gateway` client crashed on `...v1.Resource`).
- `core/gateway_common.py`: `make_rs256_verifier` verifies Identity Platform (`https://securetoken.google.com/<p>`) and Google (`https://accounts.google.com`) issuers in pure Python against the simulator's own key (no network, works on Nano); other issuers behave as before.
- Tests: `tests/conformance/test_gcp_identity_gateway_sdk.py` (27 checks, real SDKs; SKIPs, never passes, when the SDKs are not installed). Capability entries: new `core/capabilities/gcp/identity-platform.json`, extended `apigateway.json`.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Own minimal core for Identity Platform | Firebase Auth emulator | not in the local `google-cloud-cli:emulators` image (bigtable, datastore, firestore, pubsub only); firebase-tools needs a download and the emulator signs `alg:none` tokens that `verify_firebase_token` rejects by design, so a backend verifying with real libraries could not use it |
| Reuse the iamcredentials emulator RSA key; ship a self-signed X.509 over it | a second key | one public key already signs SA ID tokens; the x509 endpoint can then serve both |
| Gateway trusts that key only for the two Google issuers | accept any local key for any issuer | a forged issuer cannot be validated by an unrelated key |

## Contract for the app lane
- Sign up / in: `POST {ep}/v1/accounts:signUp?key=KEY` and `/v1/accounts:signInWithPassword?key=KEY` body `{email,password,returnSecureToken:true}` -> `idToken, refreshToken, localId`. Project comes from the API key (create one with API Keys v2) else `x-goog-user-project`, else the simulator project. Admin: `POST {ep}/v1/projects/facilities-users/accounts` and `.../accounts:update` with `customAttributes` (JSON string). Refresh: `POST {ep}/v1/token` form `grant_type=refresh_token&refresh_token=...`.
- Verify: `google.oauth2.id_token._GOOGLE_APIS_CERTS_URL = f"{ep}/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"`, then `id_token.verify_firebase_token(tok, Request(), audience=PROJECT)` (checks signature, aud, exp; also check `iss == https://securetoken.google.com/PROJECT`). PyJWT: `PyJWKClient(f"{ep}/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com")`. `firebase_admin.auth.verify_id_token` hard-codes Google's cert URL, so it cannot be used.
- Gateway: spec with `securityDefinitions.firebase = {type: oauth2, x-google-issuer: https://securetoken.google.com/PROJECT, x-google-jwks_uri: https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com, x-google-audiences: PROJECT}`; call `https://<defaultHostname>` is not resolvable on a laptop, so send `Host: <defaultHostname>` to the simulator origin or use `{ep}/gcpgw/<gatewayId>/path`. `Authorization: Bearer <idToken>`. SA tokens: `x-google-issuer: https://accounts.google.com`, jwks `https://www.googleapis.com/oauth2/v3/certs`, audience = the `audience` passed to `generateIdToken`.
- Backend: `x-google-backend.address` must be https. A Cloud Functions URL (`https://REGION-PROJECT.cloudfunctions.net/fn`) routes to the simulator's `/gcf/...`; any other origin needs `VYOMI_GATEWAY_BACKEND_OVERRIDES="https://alias=http://127.0.0.1:port"`. `*.run.app` Cloud Run URLs are NOT mapped yet (not proven in this lane).

## Open issues
- [ ] Cloud Armor: `compute securityPolicies` create/get keeps rules, but nothing evaluates them (no backend-service/gateway attachment surface in the simulator). Not cheap; unchanged.
- [ ] Gateway to a deployed Cloud Run function URL was not exercised (function sandbox is lane 3); the proof used a local HTTP backend through the override alias.
- [ ] Identity Platform: no phone/OAuth/MFA/tenants/email delivery; passwords PBKDF2 (20k) in the monitoring store.
- [ ] Tier gating not checked (the in-process harness skips it).
