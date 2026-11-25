"""Pure-Python Cognito + WAFv2 + API Gateway authorizers (core/identity_native, the Nano engine), through REAL boto3 over the wire router.

Runs with VYOMI_IDENTITY_NATIVE=1 so the appliance path exercises the same engine Nano loads in Pyodide.
Run: PYTHONPATH=. python3 -m pytest tests/test_identity_native.py -q   (needs boto3, fastapi, uvicorn, cryptography, PyJWT)
"""
import base64
import hashlib
import hmac
import io
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
import zipfile

import pytest

os.environ["VYOMI_IDENTITY_NATIVE"] = "1"
boto3 = pytest.importorskip("boto3")
pytest.importorskip("uvicorn")
from botocore.exceptions import ClientError  # noqa: E402

PW = "Fac!lities-2026"
VIS = lambda n: {"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True, "MetricName": n}  # noqa: E731


@pytest.fixture(scope="module")
def url():
    import uvicorn
    from fastapi import FastAPI, Request
    from core import wire_ingress
    app, router = FastAPI(), wire_ingress.appliance_router()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    from core import identity_native
    identity_native.reset()
    yield "http://127.0.0.1:%d" % port
    srv.should_exit = True


def cl(url, svc):
    return boto3.client(svc, endpoint_url=url, region_name="us-east-1", aws_access_key_id="AKIAVYOMI", aws_secret_access_key="x")


def err(fn, **kw):
    with pytest.raises(ClientError) as e:
        fn(**kw)
    return e.value.response["Error"]["Code"]


def test_engine_is_native():
    from core import identity_core
    assert identity_core.native() and identity_core.available()


def test_rs256_pure_python_matches_cryptography():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from core import identity_native as n
    sig = n.rs256_sign(b"hello")
    rsa.RSAPublicNumbers(n._E, n._N).public_key().verify(sig, b"hello", padding.PKCS1v15(), hashes.SHA256())
    assert n.rs256_verify(b"hello", sig, n._N, n._E) and not n.rs256_verify(b"hellp", sig, n._N, n._E)


def test_user_pool_lifecycle_and_tokens(url):
    idp = cl(url, "cognito-idp")
    pool = idp.create_user_pool(PoolName="facilities-users")["UserPool"]
    pid = pool["Id"]
    assert pid.startswith("us-east-1_") and pool["Arn"].endswith(pid)
    assert [p["Name"] for p in idp.list_user_pools(MaxResults=20)["UserPools"]] == ["facilities-users"]
    c = idp.create_user_pool_client(UserPoolId=pid, ClientName="web", ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"])["UserPoolClient"]
    assert idp.list_user_pool_clients(UserPoolId=pid)["UserPoolClients"][0]["ClientId"] == c["ClientId"]
    idp.admin_create_user(UserPoolId=pid, Username="maria.ops@example.com", UserAttributes=[{"Name": "email", "Value": "maria.ops@example.com"}], MessageAction="SUPPRESS")
    assert idp.admin_get_user(UserPoolId=pid, Username="maria.ops@example.com")["UserStatus"] == "FORCE_CHANGE_PASSWORD"
    assert err(idp.admin_set_user_password, UserPoolId=pid, Username="maria.ops@example.com", Password="weak", Permanent=True) == "InvalidPasswordException"
    idp.admin_set_user_password(UserPoolId=pid, Username="maria.ops@example.com", Password=PW, Permanent=True)
    a = idp.initiate_auth(ClientId=c["ClientId"], AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": "maria.ops@example.com", "PASSWORD": PW})["AuthenticationResult"]
    assert a["IdToken"].count(".") == 2 and a["TokenType"] == "Bearer" and a["ExpiresIn"] == 3600
    assert idp.get_user(AccessToken=a["AccessToken"])["Username"] == "maria.ops@example.com"
    claims = json.loads(base64.urlsafe_b64decode(a["IdToken"].split(".")[1] + "=="))
    assert claims["aud"] == c["ClientId"] and claims["token_use"] == "id" and claims["iss"].endswith(pid) and claims["email"] == "maria.ops@example.com"
    # refresh, wrong password, unknown user, disabled flow
    r = idp.initiate_auth(ClientId=c["ClientId"], AuthFlow="REFRESH_TOKEN_AUTH", AuthParameters={"REFRESH_TOKEN": a["RefreshToken"]})["AuthenticationResult"]
    assert "RefreshToken" not in r and r["AccessToken"]
    assert err(idp.initiate_auth, ClientId=c["ClientId"], AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": "maria.ops@example.com", "PASSWORD": "nope"}) == "NotAuthorizedException"
    assert err(idp.initiate_auth, ClientId=c["ClientId"], AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": "ghost", "PASSWORD": PW}) == "NotAuthorizedException"
    assert err(idp.initiate_auth, ClientId=c["ClientId"], AuthFlow="ADMIN_USER_PASSWORD_AUTH", AuthParameters={"USERNAME": "x", "PASSWORD": PW}) == "InvalidParameterException"
    # global sign-out revokes
    time.sleep(1.1)
    idp.global_sign_out(AccessToken=a["AccessToken"])
    assert err(idp.get_user, AccessToken=a["AccessToken"]) == "NotAuthorizedException"
    assert err(idp.initiate_auth, ClientId=c["ClientId"], AuthFlow="REFRESH_TOKEN_AUTH", AuthParameters={"REFRESH_TOKEN": a["RefreshToken"]}) == "NotAuthorizedException"
    # jwks over the wire verifies the token
    jwks = json.loads(urllib.request.urlopen("%s/%s/.well-known/jwks.json" % (url, pid)).read())
    from core import identity_native as n
    assert jwks["keys"][0]["kid"] == n.KID and n.jwt_decode(a["IdToken"])["sub"] == claims["sub"]
    oidc = json.loads(urllib.request.urlopen("%s/%s/.well-known/openid-configuration" % (url, pid)).read())
    assert oidc["issuer"].endswith(pid) and oidc["jwks_uri"].endswith("/jwks.json")


def test_signup_confirm_challenge_secret_groups(url):
    idp = cl(url, "cognito-idp")
    pid = idp.create_user_pool(PoolName="p2", AutoVerifiedAttributes=["email"], UsernameAttributes=["email"])["UserPool"]["Id"]
    c = idp.create_user_pool_client(UserPoolId=pid, ClientName="sec", GenerateSecret=True,
                                    ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_ADMIN_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"])["UserPoolClient"]
    cid, sec = c["ClientId"], c["ClientSecret"]
    sh = lambda u: base64.b64encode(hmac.new(sec.encode(), (u + cid).encode(), hashlib.sha256).digest()).decode()  # noqa: E731
    assert err(idp.sign_up, ClientId=cid, Username="joe@example.com", Password=PW) == "NotAuthorizedException"      # no SECRET_HASH
    s = idp.sign_up(ClientId=cid, Username="joe@example.com", Password=PW, SecretHash=sh("joe@example.com"))
    assert s["UserConfirmed"] is False and s["CodeDeliveryDetails"]["AttributeName"] == "email"
    assert err(idp.sign_up, ClientId=cid, Username="joe@example.com", Password=PW, SecretHash=sh("joe@example.com")) == "UsernameExistsException"
    kw = dict(ClientId=cid, AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": "joe@example.com", "PASSWORD": PW, "SECRET_HASH": sh("joe@example.com")})
    assert err(idp.initiate_auth, **kw) == "UserNotConfirmedException"
    idp.confirm_sign_up(ClientId=cid, Username="joe@example.com", ConfirmationCode="123456", SecretHash=sh("joe@example.com"))
    assert idp.initiate_auth(**kw)["AuthenticationResult"]["AccessToken"]
    assert idp.list_users(UserPoolId=pid, Filter='email = "joe@example.com"')["Users"][0]["UserStatus"] == "CONFIRMED"
    # NEW_PASSWORD_REQUIRED
    idp.admin_create_user(UserPoolId=pid, Username="sam@example.com", TemporaryPassword="Temp!pass1A", MessageAction="SUPPRESS")
    ch = idp.admin_initiate_auth(UserPoolId=pid, ClientId=cid, AuthFlow="ADMIN_USER_PASSWORD_AUTH",
                                 AuthParameters={"USERNAME": "sam@example.com", "PASSWORD": "Temp!pass1A", "SECRET_HASH": sh("sam@example.com")})
    assert ch["ChallengeName"] == "NEW_PASSWORD_REQUIRED"
    done = idp.respond_to_auth_challenge(ClientId=cid, ChallengeName="NEW_PASSWORD_REQUIRED", Session=ch["Session"],
                                         ChallengeResponses={"USERNAME": "sam@example.com", "NEW_PASSWORD": PW, "SECRET_HASH": sh("sam@example.com")})
    assert done["AuthenticationResult"]["IdToken"]
    # groups land in the token
    idp.create_group(UserPoolId=pid, GroupName="ops")
    idp.admin_add_user_to_group(UserPoolId=pid, Username="sam@example.com", GroupName="ops")
    a = idp.admin_initiate_auth(UserPoolId=pid, ClientId=cid, AuthFlow="ADMIN_USER_PASSWORD_AUTH",
                                AuthParameters={"USERNAME": "sam@example.com", "PASSWORD": PW, "SECRET_HASH": sh("sam@example.com")})["AuthenticationResult"]
    assert json.loads(base64.urlsafe_b64decode(a["IdToken"].split(".")[1] + "=="))["cognito:groups"] == ["ops"]
    assert [g["GroupName"] for g in idp.admin_list_groups_for_user(UserPoolId=pid, Username="sam@example.com")["Groups"]] == ["ops"]
    assert err(idp.describe_user_pool, UserPoolId="us-east-1_nope") == "ResourceNotFoundException"


def test_wafv2_crud_locks_and_errors(url):
    waf = cl(url, "wafv2")
    acl = waf.create_web_acl(Name="crud", Scope="REGIONAL", DefaultAction={"Allow": {}}, VisibilityConfig=VIS("crud"), Rules=[])["Summary"]
    assert acl["ARN"].startswith("arn:aws:wafv2:us-east-1:123456789012:regional/webacl/crud/")
    assert err(waf.create_web_acl, Name="crud", Scope="REGIONAL", DefaultAction={"Allow": {}}, VisibilityConfig=VIS("crud")) == "WAFDuplicateItemException"
    got = waf.get_web_acl(Name="crud", Scope="REGIONAL", Id=acl["Id"])
    assert got["WebACL"]["DefaultAction"] == {"Allow": {}}
    assert err(waf.update_web_acl, Name="crud", Scope="REGIONAL", Id=acl["Id"], LockToken="stale", DefaultAction={"Block": {}}, VisibilityConfig=VIS("crud")) == "WAFOptimisticLockException"
    nl = waf.update_web_acl(Name="crud", Scope="REGIONAL", Id=acl["Id"], LockToken=got["LockToken"], DefaultAction={"Block": {}}, VisibilityConfig=VIS("crud"))["NextLockToken"]
    assert waf.get_web_acl(Name="crud", Scope="REGIONAL", Id=acl["Id"])["WebACL"]["DefaultAction"] == {"Block": {}}
    bad = {"Name": "r", "Priority": 1, "Action": {"Block": {}}, "Statement": {"RateBasedStatement": {"Limit": 100, "AggregateKeyType": "IP"}}, "VisibilityConfig": VIS("r")}
    assert err(waf.check_capacity, Scope="REGIONAL", Rules=[bad, dict(bad, Name="r2")]) == "WAFInvalidParameterException"
    assert waf.check_capacity(Scope="REGIONAL", Rules=[dict(bad, Statement={"RateBasedStatement": {"Limit": 100, "AggregateKeyType": "IP"}})])["Capacity"] >= 2
    stage = "arn:aws:apigateway:us-east-1::/restapis/abc123/stages/prod"
    waf.associate_web_acl(WebACLArn=acl["ARN"], ResourceArn=stage)
    assert waf.list_resources_for_web_acl(WebACLArn=acl["ARN"], ResourceType="API_GATEWAY")["ResourceArns"] == [stage]
    assert err(waf.delete_web_acl, Name="crud", Scope="REGIONAL", Id=acl["Id"], LockToken=nl) == "WAFAssociatedItemException"
    waf.disassociate_web_acl(ResourceArn=stage)
    waf.delete_web_acl(Name="crud", Scope="REGIONAL", Id=acl["Id"], LockToken=nl)
    assert err(waf.get_web_acl, Name="crud", Scope="REGIONAL", Id=acl["Id"]) == "WAFNonexistentItemException"
    names = {g["Name"] for g in waf.list_available_managed_rule_groups(Scope="REGIONAL")["ManagedRuleGroups"]}
    assert "AWSManagedRulesCommonRuleSet" in names
    rp = waf.create_regex_pattern_set(Name="rx", Scope="REGIONAL", RegularExpressionList=[{"RegexString": "^/admin"}])["Summary"]
    assert waf.get_regex_pattern_set(Name="rx", Scope="REGIONAL", Id=rp["Id"])["RegexPatternSet"]["RegularExpressionList"][0]["RegexString"] == "^/admin"


def _post(u, tok=None, data=b"{}", hdr=None):
    h = {"content-type": "application/json", **(hdr or {})}
    if tok:
        h["authorization"] = tok
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, data=data, headers=h, method="POST"))
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _zip(src):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("index.py", src)
    return b.getvalue()


def test_chapter10_flow_cognito_authorizer_waf_and_lambda_authorizer(url):
    """The Vyomi Labs chapter 10 sequence: pool + client + user + login, rate ACL, API + Cognito authorizer + ACL on the stage, call with / without token."""
    from core import identity_core
    idp, waf, ag, lam = cl(url, "cognito-idp"), cl(url, "wafv2"), cl(url, "apigateway"), cl(url, "lambda")
    pool = idp.create_user_pool(PoolName="facilities-users")["UserPool"]["Id"]
    cid = idp.create_user_pool_client(UserPoolId=pool, ClientName="facilities-web", ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"])["UserPoolClient"]["ClientId"]
    idp.admin_create_user(UserPoolId=pool, Username="maria.ops@example.com", UserAttributes=[{"Name": "email", "Value": "maria.ops@example.com"}], MessageAction="SUPPRESS")
    idp.admin_set_user_password(UserPoolId=pool, Username="maria.ops@example.com", Password=PW, Permanent=True)
    tok = idp.initiate_auth(ClientId=cid, AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": "maria.ops@example.com", "PASSWORD": PW})["AuthenticationResult"]["IdToken"]
    acl = waf.create_web_acl(Name="facilities-acl", Scope="REGIONAL", DefaultAction={"Allow": {}}, VisibilityConfig=VIS("facilities-acl"), Rules=[
        {"Name": "rate", "Priority": 1, "Action": {"Block": {}}, "Statement": {"RateBasedStatement": {"Limit": 100, "AggregateKeyType": "IP"}}, "VisibilityConfig": VIS("rate")},
        {"Name": "common", "Priority": 2, "OverrideAction": {"None": {}}, "Statement": {"ManagedRuleGroupStatement": {"VendorName": "AWS", "Name": "AWSManagedRulesCommonRuleSet"}},
         "VisibilityConfig": VIS("common")}])["Summary"]
    api = ag.create_rest_api(name="facilities-api")["id"]
    root = next(r["id"] for r in ag.get_resources(restApiId=api)["items"] if r["path"] == "/")
    res = ag.create_resource(restApiId=api, parentId=root, pathPart="search")["id"]
    az = ag.create_authorizer(restApiId=api, name="cognito", type="COGNITO_USER_POOLS", identitySource="method.request.header.Authorization",
                              providerARNs=["arn:aws:cognito-idp:us-east-1:123456789012:userpool/%s" % pool])["id"]
    ag.put_method(restApiId=api, resourceId=res, httpMethod="POST", authorizationType="COGNITO_USER_POOLS", authorizerId=az)
    ag.put_integration(restApiId=api, resourceId=res, httpMethod="POST", type="MOCK", requestTemplates={"application/json": '{"statusCode": 200}'})
    ag.put_method_response(restApiId=api, resourceId=res, httpMethod="POST", statusCode="200")
    ag.put_integration_response(restApiId=api, resourceId=res, httpMethod="POST", statusCode="200", responseTemplates={"application/json": '{"results": []}'})
    ag.create_deployment(restApiId=api, stageName="prod")
    waf.associate_web_acl(WebACLArn=acl["ARN"], ResourceArn="arn:aws:apigateway:us-east-1::/restapis/%s/stages/prod" % api)
    u = "%s/restapis/%s/prod/_user_request_/search" % (url, api)
    assert _post(u)[0] == 401                                     # anonymous
    assert _post(u, "not.a.jwt")[0] == 401
    assert _post(u, tok)[0] == 200                                # Cognito ID token, no Bearer prefix (as the lab sends it)
    assert _post(u, "Bearer " + tok)[0] == 200
    forged = tok.rsplit(".", 1)[0] + "." + base64.urlsafe_b64encode(b"x" * 256).decode().rstrip("=")
    assert _post(u, forged)[0] == 401
    assert _post(u, tok, data=b'{"q": "<script>alert(1)</script>"}')[0] == 403   # managed Common rule set stub (XSS in body)
    codes = [_post(u, tok)[0] for _ in range(105)]
    assert codes[0] == 200 and codes[-1] == 403                    # rate-based rule
    identity_core.reset_rate()
    # deleted pool: tokens it signed stop validating (fail closed)
    idp.delete_user_pool(UserPoolId=pool)
    waf.disassociate_web_acl(ResourceArn="arn:aws:apigateway:us-east-1::/restapis/%s/stages/prod" % api)
    assert _post(u, tok)[0] == 401


def test_lambda_request_authorizer_enforced(url):
    lam, ag = cl(url, "lambda"), cl(url, "apigateway")
    src = ("def handler(event, context):\n    ok = (event.get('headers') or {}).get('x-api-token') == 'let-me-in'\n"
           "    return {'principalId': 'u1', 'policyDocument': {'Version': '2012-10-17', 'Statement': [{'Action': 'execute-api:Invoke', 'Effect': 'Allow' if ok else 'Deny', 'Resource': event['methodArn']}]}, 'context': {'tenant': 'acme'}}\n")
    lam.create_function(FunctionName="req-auth", Runtime="python3.12", Role="arn:aws:iam::123456789012:role/r", Handler="index.handler", Code={"ZipFile": _zip(src)})
    api = ag.create_rest_api(name="req-api")["id"]
    root = next(r["id"] for r in ag.get_resources(restApiId=api)["items"] if r["path"] == "/")
    res = ag.create_resource(restApiId=api, parentId=root, pathPart="x")["id"]
    az = ag.create_authorizer(restApiId=api, name="req", type="REQUEST", identitySource="method.request.header.x-api-token",
                              authorizerUri="arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:123456789012:function:req-auth/invocations")["id"]
    ag.put_method(restApiId=api, resourceId=res, httpMethod="POST", authorizationType="CUSTOM", authorizerId=az)
    ag.put_integration(restApiId=api, resourceId=res, httpMethod="POST", type="MOCK", requestTemplates={"application/json": '{"statusCode": 200}'})
    ag.put_method_response(restApiId=api, resourceId=res, httpMethod="POST", statusCode="200")
    ag.put_integration_response(restApiId=api, resourceId=res, httpMethod="POST", statusCode="200", responseTemplates={"application/json": '{"ok": true}'})
    ag.create_deployment(restApiId=api, stageName="prod")
    u = "%s/restapis/%s/prod/_user_request_/x" % (url, api)
    assert _post(u)[0] in (401, 403)
    assert _post(u, hdr={"x-api-token": "wrong"})[0] == 403
    assert _post(u, hdr={"x-api-token": "let-me-in"})[0] == 200
