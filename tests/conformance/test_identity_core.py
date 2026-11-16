"""C1 Access + perimeter: Cognito (moto engine) + WAFv2 + API Gateway authorizer, through REAL boto3 over the wire router.

Run: PYTHONPATH=. python3 tests/conformance/test_identity_core.py   (needs boto3, moto[cognitoidp,server], joserfc, PyJWT, cryptography)
"""
import base64, json, socket, sys, threading, time, urllib.request, urllib.error
import boto3
from botocore.config import Config

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok  {name}")
    else:
        FAIL += 1; print(f"  FAIL {name} {str(extra)[:300]}")


def server():
    import uvicorn
    from fastapi import FastAPI, Request
    from core import wire_ingress
    app = FastAPI(); router = wire_ingress.appliance_router()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}"


URL = server()
kw = dict(endpoint_url=URL, region_name="us-east-1", aws_access_key_id="AKIAVYOMI", aws_secret_access_key="x")
idp = boto3.client("cognito-idp", **kw)
cid = boto3.client("cognito-identity", **kw)
waf = boto3.client("wafv2", **kw)
apigw = boto3.client("apigateway", **kw)

# ---- Cognito
pool = idp.create_user_pool(PoolName="facilities-users", AutoVerifiedAttributes=["email"])["UserPool"]
pid = pool["Id"]
cl = idp.create_user_pool_client(UserPoolId=pid, ClientName="facilities-web", ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_ADMIN_USER_PASSWORD_AUTH"])["UserPoolClient"]
idp.create_group(UserPoolId=pid, GroupName="facility-manager")
idp.admin_create_user(UserPoolId=pid, Username="maria", UserAttributes=[{"Name": "email", "Value": "maria@example.com"}], MessageAction="SUPPRESS")
idp.admin_set_user_password(UserPoolId=pid, Username="maria", Password="Fac!lities9", Permanent=True)
idp.admin_add_user_to_group(UserPoolId=pid, Username="maria", GroupName="facility-manager")
check("pool+client+group created", pid and cl["ClientId"])
auth = idp.initiate_auth(ClientId=cl["ClientId"], AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": "maria", "PASSWORD": "Fac!lities9"})["AuthenticationResult"]
idt, act = auth["IdToken"], auth["AccessToken"]
check("InitiateAuth returns ID/access/refresh tokens", idt and act and auth.get("RefreshToken"))
check("GetUser with access token", idp.get_user(AccessToken=act)["Username"] == "maria")
try:
    idp.initiate_auth(ClientId=cl["ClientId"], AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": "maria", "PASSWORD": "wrong"}); ok = False
except idp.exceptions.NotAuthorizedException:
    ok = True
check("wrong password -> NotAuthorizedException (modeled)", ok)
sg = idp.sign_up(ClientId=cl["ClientId"], Username="joe", Password="Fac!lities9", UserAttributes=[{"Name": "email", "Value": "joe@example.com"}])
idp.admin_confirm_sign_up(UserPoolId=pid, Username="joe")
check("SignUp + confirm", sg["UserConfirmed"] is False and idp.admin_get_user(UserPoolId=pid, Username="joe")["UserStatus"] == "CONFIRMED")
# JWKS + real RS256 verify with a standard JWT library
jwks = json.loads(urllib.request.urlopen(f"{URL}/{pid}/.well-known/jwks.json").read())
check("JWKS served over the wire", jwks.get("keys"))
import jwt
from jwt import PyJWK
key = PyJWK(jwks["keys"][0]).key
iss = f"https://cognito-idp.us-east-1.amazonaws.com/{pid}"
claims = jwt.decode(idt, key, algorithms=["RS256"], audience=cl["ClientId"], issuer=iss)
check("ID token verifies with PyJWT (RS256) and carries groups", claims.get("cognito:username") == "maria" and "facility-manager" in claims.get("cognito:groups", []), claims)
check("access token verifies (client_id)", jwt.decode(act, key, algorithms=["RS256"], options={"verify_aud": False}, issuer=iss)["client_id"] == cl["ClientId"])
idp.global_sign_out(AccessToken=act)
check("cognito-identity pool create", cid.create_identity_pool(IdentityPoolName="facilities-id", AllowUnauthenticatedIdentities=False)["IdentityPoolId"])

# ---- API Gateway (REST) + COGNITO_USER_POOLS authorizer + WAF
auth = idp.initiate_auth(ClientId=cl["ClientId"], AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": "maria", "PASSWORD": "Fac!lities9"})["AuthenticationResult"]
api = apigw.create_rest_api(name="facilities-api")
aid = api["id"]
root = apigw.get_resources(restApiId=aid)["items"][0]["id"]
res = apigw.create_resource(restApiId=aid, parentId=root, pathPart="workorders")
az = apigw.create_authorizer(restApiId=aid, name="cognito", type="COGNITO_USER_POOLS", providerARNs=[f"arn:aws:cognito-idp:us-east-1:123456789012:userpool/{pid}"], identitySource="method.request.header.Authorization")
apigw.put_method(restApiId=aid, resourceId=res["id"], httpMethod="POST", authorizationType="COGNITO_USER_POOLS", authorizerId=az["id"])
apigw.put_integration(restApiId=aid, resourceId=res["id"], httpMethod="POST", type="MOCK", requestTemplates={"application/json": '{"statusCode": 200}'})
apigw.put_method_response(restApiId=aid, resourceId=res["id"], httpMethod="POST", statusCode="200")
apigw.put_integration_response(restApiId=aid, resourceId=res["id"], httpMethod="POST", statusCode="200", responseTemplates={"application/json": '{"ok": true}'})
dep = apigw.create_deployment(restApiId=aid, stageName="prod")
inv = f"{URL}/restapis/{aid}/prod/_user_request_/workorders"


def post(tok=None, data=b"{}", hdr=None):
    h = {"content-type": "application/json", **(hdr or {})}
    if tok:
        h["authorization"] = "Bearer " + tok
    try:
        r = urllib.request.urlopen(urllib.request.Request(inv, data=data, headers=h, method="POST")); return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


check("no token -> 401", post()[0] == 401)
check("garbage token -> 401", post("a.b.c")[0] == 401)
forged = auth["IdToken"].rsplit(".", 1)[0] + "." + base64.urlsafe_b64encode(b"x" * 256).decode().rstrip("=")
check("forged signature -> 401", post(forged)[0] == 401)
check("valid Cognito ID token -> 200", post(auth["IdToken"])[0] == 200, post(auth["IdToken"]))

# WAF: IP set block + SQLi + size + rate-based, attached to the stage
ipset = waf.create_ip_set(Name="bad-ips", Scope="REGIONAL", IPAddressVersion="IPV4", Addresses=["203.0.113.0/24"])["Summary"]
acl = waf.create_web_acl(Name="facilities-acl", Scope="REGIONAL", DefaultAction={"Allow": {}}, VisibilityConfig={"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True, "MetricName": "acl"}, Rules=[
    {"Name": "bad-ips", "Priority": 0, "Action": {"Block": {}}, "Statement": {"IPSetReferenceStatement": {"ARN": ipset["ARN"], "IPSetForwardedIPConfig": {"HeaderName": "X-Forwarded-For", "FallbackBehavior": "NO_MATCH", "Position": "FIRST"}}}, "VisibilityConfig": {"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True, "MetricName": "r0"}},
    {"Name": "sqli", "Priority": 1, "Action": {"Block": {}}, "Statement": {"SqliMatchStatement": {"FieldToMatch": {"QueryString": {}}, "TextTransformations": [{"Priority": 0, "Type": "URL_DECODE"}]}}, "VisibilityConfig": {"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True, "MetricName": "r1"}},
    {"Name": "big", "Priority": 2, "Action": {"Block": {}}, "Statement": {"SizeConstraintStatement": {"FieldToMatch": {"Body": {}}, "ComparisonOperator": "GT", "Size": 100, "TextTransformations": [{"Priority": 0, "Type": "NONE"}]}}, "VisibilityConfig": {"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True, "MetricName": "r2"}},
    {"Name": "rate", "Priority": 3, "Action": {"Block": {}}, "Statement": {"RateBasedStatement": {"Limit": 100, "AggregateKeyType": "IP"}}, "VisibilityConfig": {"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True, "MetricName": "r3"}},
])["Summary"]
stage_arn = f"arn:aws:apigateway:us-east-1::/restapis/{aid}/stages/prod"
waf.associate_web_acl(WebACLArn=acl["ARN"], ResourceArn=stage_arn)
check("GetWebACLForResource", waf.get_web_acl_for_resource(ResourceArn=stage_arn)["WebACL"]["Name"] == "facilities-acl")
tok = auth["IdToken"]
check("WAF allows clean request", post(tok)[0] == 200)
check("WAF blocks IP-set source (403)", post(tok, hdr={"x-forwarded-for": "203.0.113.9"})[0] == 403)
inv_save = inv; inv = inv_save + "?q=1%27%20or%20%271%27%3D%271"
check("WAF blocks SQLi query string (403)", post(tok)[0] == 403)
inv = inv_save
check("WAF blocks oversized body (403)", post(tok, data=b"x" * 500)[0] == 403)
st = [post(tok)[0] for _ in range(105)]
check("WAF rate-based rule blocks after the limit", st[-1] == 403 and st[0] == 200, st[-3:])
waf.disassociate_web_acl(ResourceArn=stage_arn)
from core import identity_core
identity_core.reset_rate()
check("after disassociate the stage is open again", post(tok)[0] == 200)
check("list/get wafv2 CRUD", len(waf.list_web_acls(Scope="REGIONAL")["WebACLs"]) == 1 and waf.get_ip_set(Name="bad-ips", Scope="REGIONAL", Id=ipset["Id"])["IPSet"]["Addresses"])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
