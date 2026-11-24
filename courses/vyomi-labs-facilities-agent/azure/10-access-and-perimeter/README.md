# Layer 10: Access and Perimeter

_Sign-in, a verified token and a protected API edge_

**What you build:** Sign users in, carry their identity to every layer, and put a protected edge in front of the tools.

## Code, in order

### 1. Install the libraries

Chapter 1 sign users in and protects the front door: Microsoft Entra ID issues the tokens (`azure-identity`), the API Management gateway from chapter 4 verifies them with a `validate-jwt` policy, and Web Application Firewall policies sit at the edge (`azure-mgmt-frontdoor`, `azure-mgmt-network`). It needs the gateway from chapter 4. The simulator serves Entra on the same https address as everything else, which is why `azure-identity` is given it as its `authority`.

- File: [`install1.sh`](./install1.sh)

### 2. Register the app and a user in Entra

Two things to sign in: an application registration (the agent) with a client secret, and a user. This is Microsoft Graph v1.0 REST, the same calls `az ad app create`, `az ad app credential reset` and `az ad user create` make. The ids and secret are saved to `entra.json` for the next blocks (a real secret would go in Key Vault, chapter 13).

- File: [`entra.py`](./entra.py)
- Run: `python entra.py` (or `./run_all.sh 10` from the project root)
- You should see: `app registration facilities-users client_id:`

### 3. Sign in and verify the token

Two sign-ins. The application signs in with its client secret through `azure-identity`'s `ClientSecretCredential` (the client-credentials flow) and gets a JWT. The user signs in with the OAuth2 password grant on the tenant's token endpoint (what `UsernamePasswordCredential` does; this script calls the endpoint directly because the MSAL library behind that credential drops the port from the user-realm lookup URL on a local address). Then the part the backend must always do: verify the token's RS256 signature against the tenant's published signing keys (JWKS) with PyJWT and check the audience. The user's token is saved in `token.txt` (the gateway helper picks it up) and the application token in `app_token.txt`.

- File: [`sign_in.py`](./sign_in.py)
- Run: `python sign_in.py` (or `./run_all.sh 10` from the project root)
- You should see: `signed in as: maria.ops@facilities.example.com`

### 4. Turn on validate-jwt at the gateway

Replace the API policy from chapter 4 with one that also runs `validate-jwt` first: the gateway fetches the tenant's OpenID configuration, checks the signature and that the audience is your API, and answers 401 itself otherwise. It keeps the function key and the rate limit, and adds an `x-vyomi-caller` header carrying the caller's application id (the `azp` claim of a v2.0 token), so a tool can audit who called it. Then four calls prove the edge: no key, key but no token, a forged `alg=none` token, and the real token.

- File: [`protect_gateway.py`](./protect_gateway.py)
- Run: `python protect_gateway.py` (or `./run_all.sh 10` from the project root)
- You should see: `application token -> caller seen by the tool is the app id: True`

### 5. Create the WAF policies

A Web Application Firewall inspects requests at the edge for injection and similar attacks. Two real policy types, each created and read back: an Azure Front Door policy (Premium, default rule set, Prevention mode) with `azure-mgmt-frontdoor`, and an Application Gateway policy (OWASP 3.2) with `azure-mgmt-network`. The simulator stores and returns these policies; it has no layer-7 firewall engine, so it does not block attack traffic itself.

- File: [`waf.py`](./waf.py)
- Run: `python waf.py` (or `./run_all.sh 10` from the project root)
- You should see: `Application Gateway WAF policy facilitieswafgw mode: Prevention`

## It works when

- token verifies against the tenant keys
- call without key rejected
- WAF policy exists
