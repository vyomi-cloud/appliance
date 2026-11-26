# Layer 11: Access and Perimeter

_Sign-in, a verified token and a protected API edge_

**What you build:** Sign users in, carry their identity to every layer, and put a protected edge in front of the tools.

## Code, in order

### 1. Sign users in with Cognito

A user pool, an app client that allows password sign-in, one user, and a real login: InitiateAuth returns the JWT that proves who the caller is. GetUser reads the profile back with the access token. Re-running creates a second pool, so run it once.

- File: [`cognito_setup.py`](./cognito_setup.py)
- Run: `python cognito_setup.py` (or `./run_all.sh 11` from the project root)
- You should see: `id token is a JWT: True`

### 2. Add a rate-limiting web ACL

WAF sits in front of the API. This regional web ACL allows traffic by default and blocks any single IP that sends more than 100 requests in the rate window.

- File: [`waf.py`](./waf.py)
- Run: `python waf.py` (or `./run_all.sh 11` from the project root)
- You should see: `web ACL arn:aws:wafv2`

### 3. Put an API Gateway in front of the knowledge tool

A REST API with one resource, `POST /search`, protected by a Cognito authorizer and integrated with the knowledge-search Lambda from chapter 6 as a Lambda proxy. The WAF web ACL is attached to the stage. Needs chapters 6 and the two scripts above.

- File: [`api_gateway.py`](./api_gateway.py)
- Run: `python api_gateway.py` (or `./run_all.sh 11` from the project root)
- You should see: `stage prod, Cognito authorizer, WAF attached`

### 4. Call the API with a token

Signs in again, sends the JWT in the Authorization header and posts a search. The simulator serves the stage under `/restapis/<id>/prod/_user_request_/`; on AWS the URL is `https://<id>.execute-api.<region>.amazonaws.com/prod`.

- File: [`call_with_token.py`](./call_with_token.py)
- Run: `python call_with_token.py` (or `./run_all.sh 11` from the project root)
- You should see: `HTTP 200`

### 5. Call the API without a token

The authorizer rejects an anonymous caller before the Lambda ever runs.

- File: [`call_without_token.py`](./call_without_token.py)
- Run: `python call_without_token.py` (or `./run_all.sh 11` from the project root)
- You should see: `(401 or 403: True )`

### 6. Failure lab: forged, tampered and replayed tokens

The edge is only as good as its token check. This block sends the API a valid token and then five bad ones: a token with a damaged signature, one whose payload was edited to claim an admin group, an unsigned `alg: none` token, garbage, and a token whose expiry was moved into the past. Each must be rejected before any Lambda runs; the valid token must still work. Then it hammers the API with a burst to see what the web ACL's rate rule does.

- File: [`token_attacks.py`](./token_attacks.py)
- Run: `python token_attacks.py` (or `./run_all.sh 11` from the project root)
- You should see: `token attacks verified`

## It works when

- user pool exists
- sign-in returns a JWT
- web ACL with a rate rule
- the route needs the token
