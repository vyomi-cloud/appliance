import base64
import json
import os
import time
import urllib.error
import urllib.request

import boto3

cg, ag = boto3.client("cognito-idp"), boto3.client("apigateway")
pool = next(p["Id"] for p in cg.list_user_pools(MaxResults=20)["UserPools"] if p["Name"] == "facilities-users")
cid = cg.list_user_pool_clients(UserPoolId=pool)["UserPoolClients"][0]["ClientId"]
tok = cg.initiate_auth(ClientId=cid, AuthFlow="USER_PASSWORD_AUTH",
                       AuthParameters={"USERNAME": "maria.ops@example.com", "PASSWORD": "Fac!lities-2026"})["AuthenticationResult"]["IdToken"]
api = next(a["id"] for a in ag.get_rest_apis()["items"] if a["name"] == "facilities-api")
url = os.environ["AWS_ENDPOINT_URL"].rstrip("/") + "/restapis/%s/prod/_user_request_/search" % api


def post(token):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = token
    try:
        return urllib.request.urlopen(urllib.request.Request(url, data=b'{"query":"boiler pressure"}', method="POST", headers=headers), timeout=60).status
    except urllib.error.HTTPError as e:
        return e.code


b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
head, payload, sig = tok.split(".")
claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
admin = dict(claims, **{"cognito:groups": ["admin"]})
expired = dict(claims, exp=int(time.time()) - 3600)
attacks = {
    "damaged signature": ".".join([head, payload, sig[:-4] + ("AAAA" if sig[-4:] != "AAAA" else "BBBB")]),
    "payload edited to claim admin": ".".join([head, b64(admin), sig]),
    "unsigned alg:none": b64({"alg": "none", "typ": "JWT"}) + "." + payload + ".",
    "garbage": "not-a-jwt",
    "expiry moved into the past": ".".join([head, b64(expired), sig]),
}
assert post(tok) == 200, "the valid token must be accepted"
for label, bad in attacks.items():
    code = post(bad)
    assert code in (401, 403), "%s was NOT rejected (HTTP %s)" % (label, code)
    print("rejected (%d): %s" % (code, label))
assert post(None) in (401, 403)

# The rate rule from the web ACL: 100 requests per window per IP. Report what this simulator does; assert the API stays correct under load.
codes = [post(tok) for _ in range(120)]
blocked = codes.count(403) + codes.count(429)
assert set(codes) <= {200, 403, 429}, "unexpected status under load: %s" % sorted(set(codes))
print("burst of 120 valid requests: %d accepted, %d rate-limited" % (codes.count(200), blocked))
print("token attacks verified")
