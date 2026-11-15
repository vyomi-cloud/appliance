# v4/ai-identity — C1 Access and perimeter security (AWS)

Owner: identity lane (AI enterprise reference). Base: origin/v4-on-main. Purpose: Cognito user pools + Cognito Identity + WAFv2 through the
real AWS SDKs, API Gateway authorizers that accept only real Cognito RS256 JWTs, WAF enforcement on an associated API stage.

## OSS choices (thumb rule)
| Piece | OSS | License / size | Substrate | Why |
|---|---|---|---|---|
| cognito-idp, cognito-identity, wafv2 semantics + real RS256 JWT + JWKS | moto 5.2.x (+ joserfc, flask) | Apache-2.0 / 7 MB wheel, ~30 MB RAM | Mesh container (pip). Nano: NOT yet (see limits) | pure Python, 3 backends already cover groups, clients, auth flows, ACL/IPSet/RuleGroup/RegexSet CRUD; cognito-local (Node) covers far less of the API and adds a runtime |
| wire adapter | `core/identity_core.py` (hand-written, thin) | ~230 lines | both | routes by X-Amz-Target (InitiateAuth/SignUp are unsigned) / JWKS path into moto's own WSGI app in process |
| JWT verify in gateways | existing `gateway_common.make_rs256_verifier` + a local-issuer hook (`identity_core.local_jwks`) | cryptography | Mesh | pool issuer resolves in process, no network; unknown pool fails closed |
| WAF enforcement | OWASP-lite evaluator in `identity_core.waf_check` (hand-written: moto stores ACLs but never evaluates) | small | both (pure Python) | Coraza/Caddy module needs an xcaddy build: documented follow-up for Mesh |

Wiring: `core/aws_wire_router.py` (service detection + dispatch branch + WAF hook before REST/HTTP API invoke), `core/gateway_common.py`
(local JWKS hook), `wasm/build_cores.py` (+ regenerated `wasm/core` mirror), `requirements.txt` (moto, PyJWT). All additive.

## Tests
`PYTHONPATH=. python3 tests/conformance/test_identity_core.py` (real boto3 over HTTP): 21/21. Covers pool `facilities-users`, client, group
`facility-manager`, user, SignUp/confirm, InitiateAuth tokens verified with PyJWT against the served JWKS, GetUser, GlobalSignOut, REST API
with COGNITO_USER_POOLS authorizer (no/garbage/forged token 401, valid token 200), WAF ACL attached to the stage (IP set, SQLi, size,
rate-based blocks 403; disassociate reopens).

## Probe (aws_probe.py, routed%)
| service | before | after |
|---|---|---|
| cognito-idp (122 ops) | 0% | 50.0% (3 ok, 58 modeled errors, 61 moto-unimplemented -> 501) |
| cognito-identity (23) | 0% | 30.4% |
| wafv2 (55) | 0% | 49.1% |
The unimplemented remainder are operations moto lacks (devices, import jobs, WebAuthn, managed login branding, terms, risk config,
Tag/UntagResource, DeleteUser, RevokeToken ...); they answer a modeled 501 NotImplementedException, not a 500.

## Declared limits / open issues
- Nano: moto + flask + joserfc are pure Python but loading them in Pyodide via micropip is NOT verified; until then Nano answers 501 for
  these services (JWT authorizers there stay un-verified as before). Mesh is the supported path.
- moto state is process-local (no Nano/appliance persistence restore); signing key is moto's static key shared by all pools.
- WAF: subset only (ByteMatch, IPSet, Size, Regex/RegexPatternSet, Sqli/Xss lite, rate-based per IP, And/Or/Not, Allow/Block/Count). Managed
  rule groups, geo, labels, CAPTCHA not evaluated. Enforced on REST (v1) and HTTP API invoke paths; CloudFront/ALB association not enforced.
- Coraza (Go, OWASP CRS) as a Caddy module: follow-up, requires xcaddy build (disk).
- HTTP API (v2) JWT authorizer gets the same Cognito JWKS hook but is not covered by a dedicated test.
- GCP/Azure equivalents (Identity Platform, Entra, Cloud Armor, Front Door WAF) not started.
