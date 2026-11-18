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

### Item 2: APIM policy expressions + Entra tokens in validate-jwt
- `core/azure_apim_expr_core.py` (new, pure Python, no eval): C# subset for `@(...)` / `@{...}` (context.Request/Response/Subscription/Api/Operation/Variables, string/Regex/Convert/LINQ helpers, `AsJwt()` claims, JObject bodies, lambdas, if/foreach).
- `core/azure_apim_gateway_core.py`: `choose/when/otherwise`, `set-variable`, `set-method`, `ip-filter` (address/range/CIDR), `validate-azure-ad-token`, `authentication-managed-identity`, outbound `set-body`, return-response ends the section (and in outbound replaces the response); `validate-jwt` verifies simulator-issued Entra tokens locally (no network) and checks tenant + endpoint version against the openid-config URL; malformed policy XML is now a 500 instead of silently ignored. Still skipped and reported in `x-vyomi-apim-skipped-policies`: cache-*, retry, send-request, validate-content, llm-*, include-fragment, etc.
### Item 3: MCP API type
- API `type`/`apiType` = `mcp`: streamable-HTTP JSON-RPC (`initialize`, `ping`, `tools/list`, `tools/call`) at `/azure-data/apim/{svc}/{api-path}`; tools from `mcpTools` (ARM REST) or all operations of `sourceApiId` (SDK `source_api_id`); a tool call is a gateway request to the source operation (its policies + backend run); MCP-level policies guard the endpoint; serviceUrl-without-tools = backend MCP pass-through. Proven with the official `mcp` client (2.3.0). No Cedar equivalent on Azure: APIM policy is the answer, nothing invented.
### Item 4: WAF
- ARM catalog entries (`core/azure_arm_data.py`) for Front Door, Application Gateway and CDN WAF policies (CRUD proven with azure-mgmt-frontdoor / -network / -cdn). `core/azure_waf_core.py` evaluates custom rules (both rule shapes, MatchRule + RateLimitRule, Allow/Block/Log/Redirect, Detection mode) in front of an APIM service whose tag `vyomi-waf-policy` names the policy. Managed rule sets are stored only; no Front Door / App Gateway data plane.
- Test: `tests/conformance/test_azure_ref_gateway_sdk.py` (+ `test_azure_apim_expr_core.py`); capabilities `azure.apim.gateway`, `azure.apim.mcpservers`, `azure.waf.*`.

## Design decisions
- No new backend: the existing Graph store + the existing simulator RSA key. One fixed key (stable across restarts, works in the browser build); a simulator key, not a secret.
- TLS is a second listener on the same app, not a proxy backend; default off so offline/Nano behaviour is unchanged.

## Open issues
- WAF association with APIM is a Vyomi tag (`vyomi-waf-policy`), because real APIM has no WAF link (Front Door/App Gateway sit in front and are not simulated).
- azure-mgmt-apimanagement 5.0.0 lacks `mcpTools`; only `source_api_id` works through the SDK.
- Console bundles rebuilt only for the nano-boot hash (wasm/v4/*/index.html, azure main.js).
- msal drops the port when building the ROPC user-realm URL: on a TLS port other than 443 add the host to `msal.authority.Authority._domains_without_user_realm_discovery` (or serve on 443).
- `aud` is the requested resource verbatim (real Entra rewrites custom API audiences to the app GUID for v2).
- No x5c in the JWKS, no key rollover, no CAE.
- Nano has no TLS listener: azure-identity cannot reach Nano.
- `test_relay_cores_parity` fails on trunk already (`azure_security_automations_core.py` missing from nano-endpoint.html); not touched here.
