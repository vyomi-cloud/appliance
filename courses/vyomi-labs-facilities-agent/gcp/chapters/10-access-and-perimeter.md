# Chapter 10: Access and Perimeter

_Sign-in, a verified token and a protected API edge_

**What you build:** Sign users in, carry their identity to every layer, and put a protected edge in front of the tools.

## Code, in order

### 1. Install the libraries

Chapter 1 signs users in, verifies who they are and puts a protected edge in front of the tools. It relies on gcp.py (chapter 10) and on the facilities-kb-search function from chapter 6, which the gateway protects. Identity Platform end-user sign-in has no Google client library (the documented client is its REST API); the rest use the official libraries.

- File: [`app/install_1.sh`](../app/install_1.sh)

### 2. Sign a user in and verify the token

Identity Platform: create the user and sign in with email and password through the identitytoolkit REST API, which returns an ID token (a JWT). Then do what your backend does with it: verify the signature, audience and issuer with google-auth against the project's public certificates. The project that owns the users is facilities-users.

- File: [`app/signin.py`](../app/signin.py)
- Run: `cd app && python signin.py`
- You should see: `verified: issuer https://securetoken.google.com/facilities-users | audience facilities-users | email maria.ops@example.com`

### 3. Give the agent its own identity

The agent is not a person: it runs as the service account agent-sa and proves who it is with an ID token generated for a given audience (IAM Credentials generateIdToken).

- File: [`app/service_account.py`](../app/service_account.py)
- Run: `cd app && python service_account.py`
- You should see: `ID token is a JWT: True`

### 4. Create the Cloud Armor policy

Cloud Armor is the web application firewall. This policy denies requests that match the preconfigured XSS rule and allows the rest. The simulator stores and returns the policy but does not evaluate its rules against traffic, so the protection you can actually observe in this lab is the JWT check at the gateway below.

- File: [`app/armor.py`](../app/armor.py)
- Run: `cd app && python armor.py`
- You should see: `policy facilities-armor with 2 rules`

### 5. Put API Gateway in front of the search tool

API Gateway takes an OpenAPI 2.0 document: x-google-backend names the backend (the kb-search function), and securityDefinitions require a valid Identity Platform JWT (issuer https://securetoken.google.com/facilities-users, audience facilities-users) or a Google ID token. This creates the API, the API config and the gateway facilities-api-gw, waiting for each to be ACTIVE.

- File: [`app/api_gateway.py`](../app/api_gateway.py)
- Run: `cd app && python api_gateway.py`
- You should see: `gateway facilities-api-gw ACTIVE`

### 6. Call the gateway with and without a token

Three calls to the gateway's /search: with the user's ID token (must be 200 and the response names the caller), with no token (must be 401) and with a forged unsigned token whose header says alg=none (must be 401). On real Google Cloud you would call https://<gateway default hostname>/search; here the simulator serves the same gateway under its own address.

- File: [`app/call_edge.py`](../app/call_edge.py)
- Run: `cd app && python call_edge.py`
- You should see: `unsigned token: 401`

## It works when

- sign-in returns an ID token that verifies
- security policy exists
- /search needs a valid token
