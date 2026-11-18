# v4/az-ref-gateway: Entra JWT + OIDC/JWKS, APIM policy expressions + MCP, WAF (Azure reference app, lane 5)

Evidence: `docs/architecture/v4.0/REF-ARCH-PROBE-AZURE.md` components 1 (Access) and 4 (Gateway).

## Changes
(filled per item below)

### Item 1: Entra tokens are real RS256 JWTs
- `core/azure_entra_tokens_core.py` (new, pure Python, Nano-loadable): mints v1/v2 access tokens, id tokens, `client_info`; publishes OIDC discovery + JWKS; reuses the RSA key of `core/gcp_iamcredentials_core` (distinct Entra `kid`).
- `core/azure_graph_core.py`: client_credentials / password / authorization_code / **refresh_token (new, rotating)** return those JWTs on `/{tenant}/oauth2/v2.0/token` and `/{tenant}/oauth2/token`; `client_secret_basic` accepted; apps now keep `appRoles`, `api.oauth2PermissionScopes`, `requiredResourceAccess` from the create body (a `Role` entry on the client is the grant that yields the `roles` claim).
- Discovery routes: `/{tenant}/v2.0/.well-known/openid-configuration`, `/{tenant}/.well-known/openid-configuration`, `/{tenant}/discovery/v2.0/keys`, `/{tenant}/discovery/keys`, `/discovery/v2.0/keys`, `/common/discovery/instance`, `/common/userrealm/{upn}` (appliance: `routes/azure_graph_unified.py` with a convertor that leaves Cognito pool ids to the AWS router; Nano: `core/aws_wire_router.py`).
- `core/azure_tls_front.py` (appliance/Mesh only, off by default): serves the same ASGI app over HTTPS (generated self-signed cert) because azure-identity/msal refuse http authorities. `VYOMI_AZURE_TLS_PORT=<port>` (0 = any), `VYOMI_AZURE_TLS=1` (9443) or `VYOMI_AZURE_REAL_BACKENDS=1`; discovery at `GET /_vyomi/azure-tls`.
- Test: `tests/conformance/test_azure_entra_jwt_sdk.py` (azure-identity ClientSecretCredential + UsernamePasswordCredential, msal ROPC/refresh/confidential, PyJWT + PyJWKClient).
- Capability: `azure.entra.tokens.jwt`.

## Design decisions
- No new backend: the existing Graph store + the existing simulator RSA key. One fixed key (stable across restarts, works in the browser build); a simulator key, not a secret.
- TLS is a second listener on the same app, not a proxy backend; default off so offline/Nano behaviour is unchanged.

## Open issues
- msal drops the port when building the ROPC user-realm URL: on a TLS port other than 443 add the host to `msal.authority.Authority._domains_without_user_realm_discovery` (or serve on 443).
- `aud` is the requested resource verbatim (real Entra rewrites custom API audiences to the app GUID for v2).
- No x5c in the JWKS, no key rollover, no CAE.
- Nano has no TLS listener: azure-identity cannot reach Nano.
- `test_relay_cores_parity` fails on trunk already (`azure_security_automations_core.py` missing from nano-endpoint.html); not touched here.
