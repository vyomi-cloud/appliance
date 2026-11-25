# Branch v4/nano-cognito-waf

Nano (in-browser Pyodide) backends for Vyomi Labs chapter 10 "Access and Perimeter": Amazon Cognito user pools, AWS WAFv2, and the API Gateway authorizers enforced on invoke. Before this branch all three answered `NotImplementedException: identity services need moto + flask + joserfc` on Nano (`docs/labs/nano-matrix-aws.md`, branch `v4/labs-nano-matrix-aws`).

## Architecture
- `core/identity_core.py` (existing wire adapter, already routed by `AwsWireRouter` for `cognito-idp`, `cognito-identity`, `wafv2`, the pool JWKS GET and the hosted-UI paths) now has two engines: moto when it is installed (appliance), else `core/identity_native.py`. `native()` is true on Nano, when moto is missing, or when `VYOMI_IDENTITY_NATIVE=1`.
- `core/identity_native.py`: pure Python, no third-party imports (loads in Pyodide). Cognito (pools, app clients with optional secret and SECRET_HASH, AdminCreateUser, SignUp / ConfirmSignUp, USER_PASSWORD_AUTH, ADMIN_USER_PASSWORD_AUTH, REFRESH_TOKEN_AUTH, NEW_PASSWORD_REQUIRED, GetUser, GlobalSignOut, groups, ListUsers filters, password policy, JWKS, OIDC discovery), Cognito Identity (minimal), WAFv2 (web ACL, IP set, regex pattern set CRUD with lock tokens, Associate / GetWebACLForResource, CheckCapacity, managed rule group listing and signature stubs).
- JWTs are RS256 signed in pure Python with one static simulator key (kid `vyomi-cognito-key-1`). `core/gateway_common.py` verifies RS256 with `identity_native.rs256_verify` when `cryptography` is absent (Pyodide), so the existing COGNITO_USER_POOLS authorizer, JWT authorizer and Lambda REQUEST/TOKEN authorizer (core/apigateway_gateway.py) need no change.
- WAF enforcement stays in `identity_core.waf_check` (byte match, IP set, size, regex, SQLi/XSS, rate-based, And/Or/Not); it now also evaluates AWS managed rule groups as signature stubs when the native engine is on (Common, SQLi, KnownBadInputs, AdminProtection, Linux; IpReputation / AnonymousIp never match).
- Registered in `wasm/build_cores.py` and `wasm/nano-boot.js` (CORES); `wasm/core/*` regenerated. No new service worker route: the router already dispatches by `X-Amz-Target`.

## Decisions
- Reuse the existing adapter and gateway; add one engine behind it rather than a second core and registry entry. Rejected: micropip-loading moto + flask + joserfc in Pyodide (large, unverified, native deps), and a separate `cognito_core` (would duplicate routing and hosted UI).
- ConfirmSignUp accepts any non-empty code (no email / SMS delivery), as moto does.

## Verified here
- `tests/test_identity_native.py` (7 tests, boto3 over the wire router, native engine): pool/client/user/auth flows, secret hash, challenge, revocation, JWKS, WAF CRUD and lock tokens, chapter 10 flow with managed rule and rate rule, Lambda REQUEST authorizer.
- `tests/conformance/test_identity_core.py` (21 checks) passes with `VYOMI_IDENTITY_NATIVE=1`.
- Headless Chrome on Nano: chapter 10's five blocks pass (see report); blocks 4 and 5 need the runner's urllib to work (below).

## Open
- Labs runner (`wasm/labs/pyrun-worker.js`, other owner): `urllib.request` has no sockets in Pyodide, so `call_with_token.py` / `call_without_token.py` fail with `URLError: timed out` until the runner patches urllib (gap 7 of the matrix). Block 4 also needs the `facilities-kb-search` Lambda (chapter 6) to run on Nano's Lambda sandbox.
- State is process-local (a reload starts empty). Static signing key shared by all pools. No SRP, MFA, federation, email / SMS. Managed rule groups are signature stubs, not the AWS rule sets.
- No console registry entry (Cognito / WAF have no v4 console page); IAM catalogs already exist. `tests/conformance/test_service_inventory.py::test_inventory_is_current` is stale on the trunk independent of this branch.
