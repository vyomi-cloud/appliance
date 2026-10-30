"""API Gateway V2 core conformance — host + Pyodide. Lifecycle for every resource kind,
real error codes, pagination, tags, quick-create, and HTTP-API invoke (Lambda proxy 2.0)."""
import json
import types

try:
    from core import apigatewayv2_core as gw, lambda_core as lam
except ImportError:  # pragma: no cover - Pyodide flat layout
    import apigatewayv2_core as gw  # type: ignore
    import lambda_core as lam  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or gw.ApiGwV2Store()

    def call(m, p, b=None, q=None):
        r = gw.dispatch(s, m, p, q or {}, {}, json.dumps(b).encode() if b is not None else b"")
        return r.status, (json.loads(r.body) if r.body else None), r.headers

    st, api, _ = call("POST", "/v2/apis", {"name": "orders", "protocolType": "HTTP", "description": "d"})
    _check("CreateApi 201 + apiId/apiEndpoint", st == 201 and api["apiId"] and api["apiEndpoint"].startswith("https://"))
    aid = api["apiId"]
    st, b, h = call("POST", "/v2/apis", {"name": "x"})
    _check("CreateApi missing protocolType → BadRequestException 400",
           st == 400 and h["x-amzn-ErrorType"] == "BadRequestException")
    st, b, h = call("GET", "/v2/apis/nope")
    _check("GetApi unknown → NotFoundException 404", st == 404 and h["x-amzn-ErrorType"] == "NotFoundException")
    st, b, _ = call("PATCH", f"/v2/apis/{aid}", {"name": "orders2", "corsConfiguration": {"allowOrigins": ["*"]}})
    _check("UpdateApi", st == 200 and b["name"] == "orders2" and b["corsConfiguration"]["allowOrigins"] == ["*"])
    st, _, _ = call("DELETE", f"/v2/apis/{aid}/cors")
    _check("DeleteCorsConfiguration 204", st == 204 and "corsConfiguration" not in call("GET", f"/v2/apis/{aid}")[1])

    # integration → route → stage → deployment
    st, integ, _ = call("POST", f"/v2/apis/{aid}/integrations", {
        "integrationType": "AWS_PROXY", "integrationUri": "arn:aws:lambda:us-east-1:000000000000:function:hello",
        "payloadFormatVersion": "2.0"})
    _check("CreateIntegration", st == 201 and integ["integrationId"] and integ["timeoutInMillis"] == 30000)
    st, _, h = call("POST", f"/v2/apis/{aid}/integrations", {"integrationType": "BOGUS"})
    _check("CreateIntegration bad type → 400", st == 400)
    iid = integ["integrationId"]
    st, route, _ = call("POST", f"/v2/apis/{aid}/routes", {"routeKey": "GET /hello/{name}", "target": f"integrations/{iid}"})
    _check("CreateRoute", st == 201 and route["routeId"] and route["authorizationType"] == "NONE")
    rid = route["routeId"]
    st, _, _ = call("POST", f"/v2/apis/{aid}/routes", {"routeKey": "GET /hello/{name}"})
    _check("duplicate route key → ConflictException 409", st == 409)
    st, _, _ = call("POST", f"/v2/apis/{aid}/routes", {"routeKey": "nonsense"})
    _check("invalid route key → 400", st == 400)
    st, r2, _ = call("PATCH", f"/v2/apis/{aid}/routes/{rid}", {"operationName": "hello"})
    _check("UpdateRoute", st == 200 and r2["operationName"] == "hello" and r2["routeKey"] == "GET /hello/{name}")
    st, rr, _ = call("POST", f"/v2/apis/{aid}/routes/{rid}/routeresponses", {"routeResponseKey": "$default"})
    _check("CreateRouteResponse", st == 201 and rr["routeResponseId"])
    st, lst, _ = call("GET", f"/v2/apis/{aid}/routes/{rid}/routeresponses")
    _check("GetRouteResponses", len(lst["items"]) == 1)
    st, ir, _ = call("POST", f"/v2/apis/{aid}/integrations/{iid}/integrationresponses", {"integrationResponseKey": "$default"})
    _check("CreateIntegrationResponse", st == 201 and ir["integrationResponseId"])

    st, stg, _ = call("POST", f"/v2/apis/{aid}/stages", {"stageName": "prod", "autoDeploy": False})
    _check("CreateStage", st == 201 and stg["stageName"] == "prod")
    st, _, _ = call("POST", f"/v2/apis/{aid}/stages", {"stageName": "prod"})
    _check("duplicate stage → 409", st == 409)
    st, dep, _ = call("POST", f"/v2/apis/{aid}/deployments", {"stageName": "prod", "description": "v1"})
    _check("CreateDeployment DEPLOYED + attached to stage",
           st == 201 and dep["deploymentStatus"] == "DEPLOYED"
           and call("GET", f"/v2/apis/{aid}/stages/prod")[1]["deploymentId"] == dep["deploymentId"])
    st, sg, _ = call("PATCH", f"/v2/apis/{aid}/stages/prod", {"stageVariables": {"a": "b"}})
    _check("UpdateStage", sg["stageVariables"] == {"a": "b"})

    st, au, _ = call("POST", f"/v2/apis/{aid}/authorizers", {
        "authorizerType": "JWT", "identitySource": ["$request.header.Authorization"], "name": "jwt",
        "jwtConfiguration": {"audience": ["a"], "issuer": "https://issuer.example.com"}})
    _check("CreateAuthorizer JWT", st == 201 and au["authorizerId"])
    st, _, _ = call("POST", f"/v2/apis/{aid}/authorizers", {"authorizerType": "JWT", "identitySource": ["x"], "name": "bad"})
    _check("JWT authorizer without jwtConfiguration → 400", st == 400)
    st, md, _ = call("POST", f"/v2/apis/{aid}/models", {"name": "Pet", "schema": "{}"})
    _check("CreateModel default contentType", st == 201 and md["contentType"] == "application/json")

    # tags
    arn = f"arn:aws:apigateway:us-east-1::/apis/{aid}"
    from urllib.parse import quote
    st, _, _ = call("POST", f"/v2/tags/{quote(arn, safe='')}", {"tags": {"env": "dev", "team": "x"}})
    _check("TagResource 201", st == 201)
    _check("GetTags", call("GET", f"/v2/tags/{quote(arn, safe='')}")[1]["tags"] == {"env": "dev", "team": "x"})
    call("DELETE", f"/v2/tags/{quote(arn, safe='')}", None, {"tagKeys": ["team"]})
    _check("UntagResource", call("GET", f"/v2/tags/{quote(arn, safe='')}")[1]["tags"] == {"env": "dev"})

    # domain + mapping + vpc link
    st, dom, _ = call("POST", "/v2/domainnames", {"domainName": "api.example.com"})
    _check("CreateDomainName", st == 201 and dom["domainNameArn"].endswith("/domainnames/api.example.com"))
    _check("duplicate domain → 409", call("POST", "/v2/domainnames", {"domainName": "api.example.com"})[0] == 409)
    st, mp, _ = call("POST", "/v2/domainnames/api.example.com/apimappings", {"apiId": aid, "stage": "prod"})
    _check("CreateApiMapping", st == 201 and mp["apiMappingId"])
    st, vl, _ = call("POST", "/v2/vpclinks", {"name": "vl", "subnetIds": ["subnet-1"]})
    _check("CreateVpcLink AVAILABLE", st == 201 and vl["vpcLinkStatus"] == "AVAILABLE")
    _check("DeleteVpcLink 202", call("DELETE", f"/v2/vpclinks/{vl['vpcLinkId']}")[0] == 202)

    # domain name access association (private custom domain ↔ VPC endpoint)
    st, assoc, _ = call("POST", "/v2/domainnameaccessassociations",
                        {"domainNameArn": dom["domainNameArn"], "accessAssociationSourceType": "VPCE", "accessAssociationSource": "vpce-123"})
    _check("CreateDomainNameAccessAssociation", st == 201 and assoc["domainNameAccessAssociationArn"])
    aaid = assoc["domainNameAccessAssociationArn"]
    _check("bad source type rejected", call("POST", "/v2/domainnameaccessassociations",
           {"domainNameArn": dom["domainNameArn"], "accessAssociationSourceType": "X", "accessAssociationSource": "y"})[0] == 400)
    _check("unknown domain rejected", call("POST", "/v2/domainnameaccessassociations",
           {"domainNameArn": "arn:aws:apigateway:us-east-1::/domainnames/nope", "accessAssociationSourceType": "VPCE", "accessAssociationSource": "y"})[0] == 404)
    st, lst, _ = call("GET", "/v2/domainnameaccessassociations", None, {"domainNameArn": dom["domainNameArn"]})
    _check("GetDomainNameAccessAssociations filters by domain", st == 200 and len(lst["items"]) == 1)
    from urllib.parse import quote as _q
    st, got, _ = call("GET", f"/v2/domainnameaccessassociations/{_q(aaid, safe='')}")
    _check("GetDomainNameAccessAssociation", st == 200 and got["accessAssociationSource"] == "vpce-123")
    _check("DeleteDomainNameAccessAssociation", call("DELETE", f"/v2/domainnameaccessassociations/{_q(aaid, safe='')}")[0] == 202)
    _check("gone after delete", call("GET", f"/v2/domainnameaccessassociations/{_q(aaid, safe='')}")[0] == 404)

    # pagination
    for i in range(3):
        call("POST", "/v2/apis", {"name": f"p{i}", "protocolType": "WEBSOCKET", "routeSelectionExpression": "$request.body.action"})
    st, p1, _ = call("GET", "/v2/apis", None, {"maxResults": "2"})
    st, p2, _ = call("GET", "/v2/apis", None, {"maxResults": "2", "nextToken": p1["nextToken"]})
    _check("GetApis pagination", len(p1["items"]) == 2 and len(p2["items"]) == 2 and "nextToken" not in p2)

    # quick create + invoke (Lambda proxy payload 2.0)
    lam.dispatch(s, "POST", "/2015-03-31/functions", {}, {}, json.dumps({
        "FunctionName": "hello", "Runtime": "python3.12", "Handler": "index.handler", "Role": "arn:aws:iam::0:role/r",
        "Code": {"ZipFile": ("def handler(event, ctx):\n    return {'statusCode': 200, 'body': 'hi ' + event['pathParameters']['name']}\n")},
    }).encode())
    out = gw.invoke(s, aid, "prod", "GET", "/hello/bob", lambda_store=s)
    _check("invoke → Lambda proxy v2 → 200 'hi bob'", out.status == 200 and out.body == b"hi bob")
    _check("invoke unmatched → 404", gw.invoke(s, aid, "prod", "GET", "/nope", lambda_store=s).status == 404)
    st, qc, _ = call("POST", "/v2/apis", {"name": "qc", "protocolType": "HTTP", "target": "https://example.com"})
    qid = qc["apiId"]
    _check("quick create makes $default route/integration/stage",
           len(call("GET", f"/v2/apis/{qid}/routes")[1]["items"]) == 1
           and call("GET", f"/v2/apis/{qid}/stages/$default")[1]["autoDeploy"] is True)

    _check("DeleteApi 204", call("DELETE", f"/v2/apis/{aid}")[0] == 204)
    _check("GetApi after delete → 404", call("GET", f"/v2/apis/{aid}")[0] == 404)
    return s


def test_apigatewayv2_core():
    run()


if __name__ == "__main__":
    run()
    print("apigatewayv2 core: PASS")
