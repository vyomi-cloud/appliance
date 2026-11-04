"""APIM gateway data plane: routing, subscription keys, policies, analytics + capacity (hermetic, no network).
Run: PYTHONPATH=. python tests/conformance/test_azure_apim_gateway_core.py"""
import base64, hashlib, hmac, json
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
from core import azure_apim_gateway_core as gw

AzureArm.STRICT_SUBSCRIPTION = False


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def jwt(claims, key=b"k3y", alg="HS256"):
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    h, p = b({"alg": alg, "typ": "JWT"}), b(claims)
    sig = base64.urlsafe_b64encode(hmac.new(key, f"{h}.{p}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{h}.{p}.{sig}"


def pol(inbound="", backend="", outbound=""):
    return {"properties": {"format": "xml", "value": f"<policies><inbound><base />{inbound}</inbound><backend>{backend or '<base />'}</backend><outbound><base />{outbound}</outbound><on-error><base /></on-error></policies>"}}


def run():
    a = AzureArm()
    Q = {"api-version": "2022-08-01"}
    S = f"/subscriptions/{SUB}/resourceGroups/gw-rg"
    put = lambda p, b: a.handle("PUT", S + p, Q, b)
    put("", {"location": "eastus"})
    base = "/providers/Microsoft.ApiManagement/service/gwsvc"
    put(base, {"location": "eastus", "sku": {"name": "Developer", "capacity": 1}, "properties": {"publisherEmail": "a@b.c", "publisherName": "x"}})
    put(base + "/apis/echo", {"properties": {"displayName": "Echo", "path": "echo", "serviceUrl": "http://backend.local/base", "protocols": ["https"], "subscriptionRequired": True}})
    put(base + "/apis/open", {"properties": {"displayName": "Open", "path": "open", "serviceUrl": "http://backend.local", "subscriptionRequired": False}})
    for api in ("echo", "open"):
        put(f"{base}/apis/{api}/operations/get1", {"properties": {"displayName": "get1", "method": "GET", "urlTemplate": "/r/{id}"}})
    put(base + "/apis/echo/operations/mock", {"properties": {"displayName": "mock", "method": "GET", "urlTemplate": "/mock",
        "responses": [{"statusCode": 200, "representations": [{"contentType": "application/json", "sample": '{"hello":"mock"}'}]}]}})
    put(base + "/apis/echo/operations/jwt", {"properties": {"displayName": "jwt", "method": "GET", "urlTemplate": "/secure"}})
    put(base + "/products/p1", {"properties": {"displayName": "p1", "subscriptionRequired": True}})
    put(base + "/subscriptions/s1", {"properties": {"scope": f"{S}{base}/apis", "displayName": "s1"}})
    put(base + "/subscriptions/s-open", {"properties": {"scope": f"{S}{base}/apis/open", "displayName": "other"}})
    put(base + "/subscriptions/s-susp", {"properties": {"scope": f"{S}{base}/apis", "displayName": "susp", "state": "suspended"}})
    put(base + "/backends/b2", {"properties": {"url": "http://other.local/b2", "protocol": "http"}})
    svc = gw.find_service(a.state, "gwsvc")
    _check("service found", svc is not None)
    key = a.handle("POST", S + base + "/subscriptions/s1/listSecrets", Q)["body"]["primaryKey"]
    seen = []

    def fetch(m, url, h, d):
        seen.append((m, url, h, d))
        return 200, {"content-type": "application/json", "x-backend": "1"}, b'{"ok":true}'

    def call(method, path, headers=None, query=None, body=b"", now=1000.0):
        return gw.handle(a.state, svc, method, path, query or {}, headers or {}, body, fetch=fetch, now=now)

    K = {"Ocp-Apim-Subscription-Key": key}
    r = call("GET", "/nope/x")
    _check("unknown API -> 404 Resource not found", r["status"] == 404 and b"Resource not found" in r["body"])
    r = call("GET", "/echo/zzz", K)
    _check("unknown operation -> 404", r["status"] == 404)
    r = call("GET", "/echo/r/7")
    _check("missing key -> 401 missing", r["status"] == 401 and b"missing subscription key" in r["body"])
    r = call("GET", "/echo/r/7", {"Ocp-Apim-Subscription-Key": "bad"})
    _check("bad key -> 401 invalid", r["status"] == 401 and b"invalid subscription key" in r["body"])
    sk = a.handle("POST", S + base + "/subscriptions/s-susp/listSecrets", Q)["body"]["primaryKey"]
    _check("suspended sub -> 401", call("GET", "/echo/r/7", {"Ocp-Apim-Subscription-Key": sk})["status"] == 401)
    ok = a.handle("POST", S + base + "/subscriptions/s-open/listSecrets", Q)["body"]["primaryKey"]
    _check("API-scoped sub rejected on another API", call("GET", "/echo/r/7", {"Ocp-Apim-Subscription-Key": ok})["status"] == 401)
    r = call("GET", "/echo/r/7", query={"subscription-key": key})
    _check("key via query -> forwarded", r["status"] == 200 and seen[-1][1] == "http://backend.local/base/r/7")
    r = call("GET", "/open/r/1")
    _check("subscriptionRequired=false needs no key", r["status"] == 200)
    master = a.handle("POST", S + base + "/subscriptions/master/listSecrets", Q)["body"]["primaryKey"]
    _check("master key accepted", call("GET", "/echo/r/7", {"Ocp-Apim-Subscription-Key": master})["status"] == 200)
    # policies
    put(base + "/apis/echo/policies/policy", pol('<set-header name="x-added" exists-action="override"><value>yes</value></set-header>'
                                                '<set-query-parameter name="v" exists-action="override"><value>2</value></set-query-parameter>',
                                                outbound='<set-header name="x-out" exists-action="override"><value>done</value></set-header>'))
    r = call("GET", "/echo/r/7", K)
    _check("set-header inbound reaches backend", seen[-1][2].get("x-added") == "yes")
    _check("set-query-parameter applied", seen[-1][1].endswith("/r/7?v=2"))
    _check("set-header outbound on response", r["headers"].get("x-out") == "done" and r["headers"].get("x-backend") == "1")
    _check("subscription key not leaked to backend", "ocp-apim-subscription-key" not in seen[-1][2])
    put(base + "/apis/echo/operations/get1/policies/policy", pol('<rewrite-uri template="/v2/items/{id}" />'))
    call("GET", "/echo/r/9", K)
    _check("rewrite-uri substitutes {id}", seen[-1][1].startswith("http://backend.local/base/v2/items/9"))
    put(base + "/apis/echo/operations/get1/policies/policy", pol('<set-backend-service backend-id="b2" />'))
    call("GET", "/echo/r/9", K)
    _check("set-backend-service backend-id", seen[-1][1].startswith("http://other.local/b2/r/9"))
    put(base + "/apis/echo/operations/get1/policies/policy", pol('<set-backend-service base-url="http://direct.local/x" />'))
    call("GET", "/echo/r/9", K)
    _check("set-backend-service base-url", seen[-1][1].startswith("http://direct.local/x/r/9"))
    put(base + "/apis/echo/operations/get1/policies/policy", pol('<rate-limit calls="2" renewal-period="60" />'))
    codes = [call("GET", "/echo/r/1", K, now=2000.0 + i)["status"] for i in range(4)]
    _check("rate-limit 2/60s -> 200,200,429,429", codes == [200, 200, 429, 429])
    r = call("GET", "/echo/r/1", K, now=2005.0)
    _check("429 has Retry-After + message", r["headers"].get("Retry-After") and b"Rate limit is exceeded" in r["body"])
    _check("rate-limit window renews", call("GET", "/echo/r/1", K, now=2100.0)["status"] == 200)
    put(base + "/apis/echo/operations/get1/policies/policy", pol('<rate-limit-by-key calls="1" renewal-period="60" counter-key="@(context.Request.Headers.GetValueOrDefault(&quot;x-user&quot;,&quot;anon&quot;))" />'))
    c = [call("GET", "/echo/r/1", dict(K, **{"x-user": u}), now=3000.0)["status"] for u in ("a", "a", "b")]
    _check("rate-limit-by-key counts per key", c == [200, 429, 200])
    r = call("GET", "/echo/mock", K)
    _check("operation without mock hits backend", r["status"] == 200)
    put(base + "/apis/echo/operations/mock/policies/policy", pol('<mock-response status-code="200" content-type="application/json" />'))
    n = len(seen)
    r = call("GET", "/echo/mock", K)
    _check("mock-response serves the operation sample, no backend call", r["status"] == 200 and r["body"] == b'{"hello":"mock"}' and len(seen) == n)
    put(base + "/apis/echo/operations/jwt/policies/policy", pol(
        '<validate-jwt header-name="Authorization"><issuer-signing-keys><key>' + base64.b64encode(b"k3y").decode() + '</key></issuer-signing-keys>'
        '<issuers><issuer>https://iss</issuer></issuers><required-claims><claim name="role" match="any"><value>admin</value></claim></required-claims></validate-jwt>'))
    good = jwt({"iss": "https://iss", "role": "admin", "exp": 5000})
    _check("validate-jwt ok", call("GET", "/echo/secure", dict(K, Authorization="Bearer " + good), now=1000.0)["status"] == 200)
    _check("validate-jwt missing token -> 401", call("GET", "/echo/secure", K)["status"] == 401)
    _check("validate-jwt expired -> 401", call("GET", "/echo/secure", dict(K, Authorization="Bearer " + good), now=9000.0)["status"] == 401)
    _check("validate-jwt bad signature -> 401", call("GET", "/echo/secure", dict(K, Authorization="Bearer " + jwt({"iss": "https://iss", "role": "admin"}, key=b"x")))["status"] == 401)
    _check("validate-jwt wrong role -> 401", call("GET", "/echo/secure", dict(K, Authorization="Bearer " + jwt({"iss": "https://iss", "role": "user"})))["status"] == 401)
    # return-response + unsupported element reporting
    put(base + "/apis/echo/operations/jwt/policies/policy", pol('<return-response><set-status code="418" reason="teapot" /><set-body>short</set-body></return-response><find-and-replace from="a" to="b" />'))
    r = call("GET", "/echo/secure", K)
    _check("return-response short-circuits", r["status"] == 418 and r["body"] == b"short")
    # global policy composes with <base/>
    put(base + "/policies/policy", pol('<set-header name="x-global" exists-action="override"><value>g</value></set-header><find-and-replace from="a" to="b" />'))
    r = call("GET", "/open/r/1")
    _check("global policy applies to every API", seen[-1][2].get("x-global") == "g")
    _check("unsupported element reported, not silently passed", "find-and-replace" in r["headers"].get("x-vyomi-apim-skipped-policies", ""))
    # no backend + nano (fetch=None)
    r = gw.handle(a.state, svc, "GET", "/open/r/1", {}, {}, b"", fetch=None, now=1.0)
    _check("fetch=None -> honest 502", r["status"] == 502)
    # analytics
    an = gw.analytics(svc, now=3001.0, window=10000)
    _check("analytics counts real requests", an["totalRequests"] > 20 and an["byApi"]["echo"] > 10)
    _check("analytics status classes", an["statusClasses"]["4xx"] >= 8 and an["statusClasses"]["2xx"] >= 10)
    for i in range(30):
        call("GET", "/open/r/1", now=5000.0 + i)
    cap = gw.analytics(svc, now=5030.0)["capacity"]
    _check("capacity gauge derived from request rate", 0 < cap["percent"] < 100 and cap["units"] == 1)
    arm = a.handle("GET", S + base + "/vyomiAnalytics", Q)
    call("GET", "/open/r/1", now=__import__("time").time())
    arm = a.handle("GET", S + base + "/vyomiAnalytics", Q)
    _check("ARM analytics route", arm["status"] == 200 and arm["body"]["totalRequests"] >= 1 and "capacity" in arm["body"])
    # wire router path
    from core.aws_wire_router import AwsWireRouter
    AwsWireRouter.STRICT_GCP_PROJECT = False
    R = AwsWireRouter()
    R.az_arm.state.update(a.state)
    w = R.handle("GET", "/azure-data/apim/gwsvc/open/r/1", {}, {}, b"")
    _check("wire route /azure-data/apim/{svc}/... reaches the gateway", w["status"] in (200, 502))
    w = R.handle("GET", "/azure-data/apim/gwsvc/echo/r/1", {}, {}, b"")
    _check("wire route enforces the key", w["status"] == 401)
    w = R.handle("GET", "/azure-data/apim/missing/echo/r/1", {}, {}, b"")
    _check("unknown service 404", w["status"] == 404)
    print("ALL OK")


if __name__ == "__main__":
    run()
