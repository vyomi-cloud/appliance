"""C1: Cognito sign-in, WAF web ACL, API Gateway in front of the tools (JWT authorizer)."""
import json, urllib.request
from ..runtime import NAMES, Blocked

USER, PW = "maria.ops@example.com", "Fac!lities-2026"


def sign_in(ctx):
    cg = ctx.client("cognito-idp")
    pool = ctx.step("cognito: CreateUserPool facilities-users", lambda: cg.create_user_pool(PoolName=NAMES["pool"])["UserPool"]["Id"], lane="identity")
    if not pool:
        ctx.step("cognito: sign-in (AdminCreateUser, InitiateAuth -> JWT)", lambda: (_ for _ in ()).throw(Blocked("identity", "no user pool")))
        ctx.state["user"] = "anonymous (no identity provider yet)"
        return
    ctx.state["pool_id"] = pool
    cid = ctx.step("cognito: CreateUserPoolClient", lambda: cg.create_user_pool_client(
        UserPoolId=pool, ClientName="facilities-web", ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"])["UserPoolClient"]["ClientId"])

    def login():
        cg.admin_create_user(UserPoolId=pool, Username=USER, UserAttributes=[{"Name": "email", "Value": USER}], MessageAction="SUPPRESS")
        cg.admin_set_user_password(UserPoolId=pool, Username=USER, Password=PW, Permanent=True)
        r = cg.initiate_auth(ClientId=cid, AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": USER, "PASSWORD": PW})
        tok = r["AuthenticationResult"]["IdToken"]
        assert tok.count(".") == 2, "IdToken is not a JWT"
        ctx.state["jwt"] = tok
        ctx.state["access"] = r["AuthenticationResult"]["AccessToken"]
        ctx.state["user"] = USER
        return f"signed in as {USER}, JWT {len(tok)} chars"
    ctx.step("cognito: AdminCreateUser + InitiateAuth -> JWT", login, lane="identity")
    ctx.step("cognito: GetUser with access token", lambda: cg.get_user(AccessToken=ctx.state.get("access", ctx.state["jwt"]))["Username"]
             if "jwt" in ctx.state else (_ for _ in ()).throw(Blocked("identity", "no token")))
    waf = ctx.client("wafv2")

    def make_acl():
        r = waf.create_web_acl(Name="facilities-acl", Scope="REGIONAL", DefaultAction={"Allow": {}},
                               VisibilityConfig={"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True, "MetricName": "facilities-acl"},
                               Rules=[{"Name": "rate", "Priority": 1, "Action": {"Block": {}},
                                       "Statement": {"RateBasedStatement": {"Limit": 100, "AggregateKeyType": "IP"}},
                                       "VisibilityConfig": {"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True, "MetricName": "rate"}}])
        ctx.state["acl_arn"] = r["Summary"]["ARN"]
        return r["Summary"]["ARN"]
    ctx.step("wafv2: CreateWebACL (rate-based rule)", make_acl, lane="identity")


def edge(ctx):
    """API Gateway REST API -> Lambda proxy (read-only knowledge search), JWT authorizer when a pool exists."""
    ag = ctx.client("apigateway")
    arn = ctx.state["kb_lambda_arn"]

    def build():
        api = ag.create_rest_api(name="facilities-api")["id"]
        root = [r for r in ag.get_resources(restApiId=api)["items"] if r["path"] == "/"][0]["id"]
        res = ag.create_resource(restApiId=api, parentId=root, pathPart="search")["id"]
        auth = {}
        if ctx.state.get("pool_id"):
            a = ag.create_authorizer(restApiId=api, name="cognito", type="COGNITO_USER_POOLS", identitySource="method.request.header.Authorization",
                                     providerARNs=[f"arn:aws:cognito-idp:{ctx.region}:123456789012:userpool/{ctx.state['pool_id']}"])["id"]
            auth = dict(authorizationType="COGNITO_USER_POOLS", authorizerId=a)
        ag.put_method(restApiId=api, resourceId=res, httpMethod="POST", **(auth or {"authorizationType": "NONE"}))
        ag.put_integration(restApiId=api, resourceId=res, httpMethod="POST", type="AWS_PROXY", integrationHttpMethod="POST",
                           uri=f"arn:aws:apigateway:{ctx.region}:lambda:path/2015-03-31/functions/{arn}/invocations")
        ag.create_deployment(restApiId=api, stageName="prod")
        ctx.state["api_id"] = api
        return api
    api = ctx.step("apigateway: REST API + /search proxy to Lambda" + (" + Cognito authorizer" if ctx.state.get("pool_id") else " (no authorizer: identity blocked)"), build)
    if not api:
        return
    if ctx.state.get("acl_arn"):
        ctx.step("wafv2: AssociateWebACL to the API stage", lambda: ctx.client("wafv2").associate_web_acl(
            WebACLArn=ctx.state["acl_arn"], ResourceArn=f"arn:aws:apigateway:{ctx.region}::/restapis/{api}/stages/prod") and "associated", lane="identity")

    def call(token):
        url = f"{ctx.endpoint}/restapis/{api}/prod/_user_request_/search"
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = token
        req = urllib.request.Request(url, data=json.dumps({"query": "boiler pressure limit"}).encode(), headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def authed():
        code, body = call(ctx.state.get("jwt"))
        assert code == 200, f"HTTP {code}: {body[:160]}"
        return f"HTTP 200 via API Gateway ({len(body)} bytes)"
    ctx.step("apigateway: invoke /search" + (" with JWT" if ctx.state.get("jwt") else " (anonymous)"), authed)
    if ctx.state.get("pool_id"):
        def anon():
            code, _ = call(None)
            assert code in (401, 403), f"unauthenticated call got HTTP {code}, expected 401/403"
            return f"unauthenticated call rejected with HTTP {code}"
        ctx.step("apigateway: request without token is rejected", anon)
