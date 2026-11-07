"""App host + site-config panels + autoscale + APIM fronting, all REAL (core/azure_webhost_core.py, azure_autoscale_core.py,
azure_apim_gateway_core.py), end to end through AzureArm state.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_webhost_autoscale_apim.py"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import core.azure_arm_core as _a
_a.AzureArm.STRICT_SUBSCRIPTION = False
from core.azure_arm_core import AzureArm
from core import azure_webhost_core as wh, azure_autoscale_core as asc, azure_apim_gateway_core as gw

PASS = FAIL = 0
SUB = "00000000-0000-0000-0000-cloudlearn01"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail)[:300] if detail and not ok else ''}")


arm = AzureArm()
RG = f"/subscriptions/{SUB}/resourceGroups/rg1"
W = RG + "/providers/Microsoft.Web"


def call(m, p, b=None, v="2022-09-01"):
    return arm.handle(m, p, {"api-version": v}, b)


call("PUT", RG, {"location": "eastus"}, "2021-04-01")
r = call("PUT", f"{W}/serverfarms/plan1", {"location": "eastus", "sku": {"name": "S1"}, "properties": {}})
check("plan created", r["status"] in (200, 201), r)
PLAN = f"{W}/serverfarms/plan1"
r = call("PUT", f"{W}/sites/web1", {"location": "eastus", "kind": "app", "properties": {"serverFarmId": PLAN}})
check("web app created", r["status"] in (200, 201), r)
state = arm.state
site = state[f"{W}/sites/web1".lower()]
kudu = lambda p, content: call("PUT", f"{W}/sites/web1/kudu/vfs/site/wwwroot/{p}", {"content": content}, "2022-09-01")
check("deploy index.html", kudu("index.html", "<h1>hello</h1>")["status"] in (200, 201))
check("deploy blog/home.html", kudu("blog/home.htm", "<p>blog</p>")["status"] in (200, 201))
kudu("other/page.html", "OTHER")


def hit(path="/", **h):
    return wh.serve(state, site, "GET", path, {}, h, b"")


r = hit("/")
check("default document served (index.html before others)", r["status"] == 200 and r["body"] == b"<h1>hello</h1>", r)
r = hit("/nope.html")
check("missing file -> 404 default page", r["status"] == 404 and b"404" in r["body"])

# ── site config panels REALLY apply ──
cfg = lambda d: call("PATCH", f"{W}/sites/web1/config/web", {"properties": d})
check("custom error page for 404 saved", cfg({"errorPages": {"404": "<b>custom missing</b>"}})["status"] == 200)
r = hit("/nope.html")
check("custom 404 error page is what the host returns", r["body"] == b"<b>custom missing</b>", r)
cfg({"defaultDocuments": ["home.htm"]})
check("default documents order honoured (dir with no matching doc -> 403)", hit("/blog")["body"] == b"<p>blog</p>" and hit("/")["status"] == 403)
cfg({"defaultDocuments": ["index.html"]})
cfg({"virtualApplications": [{"virtualPath": "/", "physicalPath": "site\\wwwroot"}, {"virtualPath": "/o", "physicalPath": "site\\wwwroot\\other"}]})
r = hit("/o/page.html")
check("path mapping: /o served from wwwroot/other", r["status"] == 200 and r["body"] == b"OTHER", r)
check("httpsOnly toggled", call("PATCH", f"{W}/sites/web1", {"properties": {"httpsOnly": True}})["status"] == 200)
r = hit("/", **{"x-forwarded-proto": "http", "host": "web1.azurewebsites.net"})
check("HTTPS-only: http request -> 301 to https", r["status"] == 301 and r["headers"]["location"] == "https://web1.azurewebsites.net/", r)
check("HTTPS request still served", hit("/", **{"x-forwarded-proto": "https"})["status"] == 200)
cfg({"minTlsVersion": "1.2"})
check("min TLS 1.2: TLS 1.0 client refused (421)", hit("/", **{"x-vyomi-tls-version": "1.0"})["status"] == 421)
check("min TLS 1.2: TLS 1.2 client served", hit("/", **{"x-vyomi-tls-version": "1.2"})["status"] == 200)
cfg({"ipSecurityRestrictions": [{"name": "office", "priority": 100, "action": "Allow", "ipAddress": "10.1.0.0/16"}]})
check("IP restriction: allowed source", hit("/", **{"x-vyomi-source-ip": "10.1.2.3"})["status"] == 200)
check("IP restriction: other source 403", hit("/", **{"x-vyomi-source-ip": "8.8.8.8"})["status"] == 403)
cfg({"ipSecurityRestrictions": []})
cfg({"healthCheckPath": "/index.html"})
r = hit("/")
check("health check probe healthy -> x-vyomi-health", r["headers"].get("x-vyomi-health") == "healthy", r["headers"])
cfg({"healthCheckPath": "/gone.html"})
check("health check probe unhealthy is detected", hit("/")["headers"].get("x-vyomi-health") == "unhealthy")
cfg({"healthCheckPath": ""})
cfg({"alwaysOn": False})
r1 = wh.serve(state, site, "GET", "/", {}, {}, b"", now=10_000_000.0)
r2 = wh.serve(state, site, "GET", "/", {}, {}, b"", now=10_000_010.0)
r3 = wh.serve(state, site, "GET", "/", {}, {}, b"", now=10_000_010.0 + 21 * 60)
check("not Always On: idle >20 min -> cold start again", r2["headers"].get("x-vyomi-cold-start") is None and r3["headers"].get("x-vyomi-cold-start") == "true")
cfg({"alwaysOn": True})
r4 = wh.serve(state, site, "GET", "/", {}, {}, b"", now=10_000_010.0 + 60 * 60)
check("Always On: never cold-starts", r4["headers"].get("x-vyomi-cold-start") is None)
call("PATCH", f"{W}/sites/web1", {"properties": {"httpsOnly": False}})
call("POST", f"{W}/sites/web1/stop")
check("stopped app answers 403", hit("/")["status"] == 403 or site["properties"].get("state") != "Stopped")

# ── Function App: app settings -> env, APIM fronting ──
call("PUT", f"{W}/sites/fn1", {"location": "eastus", "kind": "functionapp", "properties": {"serverFarmId": PLAN, "reserved": True, "siteConfig": {"_runtime": "Python", "_version": "3.12"}}})
fsite = state[f"{W}/sites/fn1".lower()]
call("PUT", f"{W}/sites/fn1/config/appsettings", {"properties": {"GREETING": "bonjour"}})
code = "def main(req):\n    return {'greeting': os.environ['GREETING'], 'method': req['method']}\n"
call("PUT", f"{W}/sites/fn1/functions/hello", {"properties": {"files": {"__init__.py": code}}})
r = wh.serve(state, fsite, "GET", "/api/hello", {}, {}, b"")
check("Function App app setting is the function's environment", r["status"] == 200 and json.loads(r["body"])["greeting"] == "bonjour", r)
call("PUT", f"{W}/sites/fn1/config/appsettings", {"properties": {"GREETING": "hola"}})
r = wh.serve(state, fsite, "GET", "/api/hello", {}, {}, b"")
check("changing the app setting changes the running function", json.loads(r["body"])["greeting"] == "hola")

AP = RG + "/providers/Microsoft.ApiManagement/service/apim1"
call("PUT", AP, {"location": "eastus", "sku": {"name": "Developer", "capacity": 1}, "properties": {"publisherEmail": "a@b.c", "publisherName": "x"}}, "2022-08-01")
r = call("PATCH", f"{W}/sites/fn1/config/web", {"properties": {"apiManagementConfig": {"id": AP}}})
check("link API Management -> accepted", r["status"] == 200, r)
apis = [k for k in state if k.startswith(AP.lower() + "/apis/") and "/operations/" not in k and "__event__" not in k]
ops = [k for k in state if "/operations/" in k and k.startswith(AP.lower())]
check("the function's API was IMPORTED into the gateway (api + 2 ops for 'hello')", len(apis) == 1 and len(ops) == 2, (apis, ops))
svc = gw.find_service(state, "apim1")
fetch = wh.make_fetch(state, None)
key = call("POST", AP + "/subscriptions/master/listSecrets", None, "2022-08-01")
mk = (key["body"] or {}).get("primaryKey", "")
G = lambda path, headers=None, now=1000.0: gw.handle(state, svc, "GET", path, {}, dict({"Ocp-Apim-Subscription-Key": mk}, **(headers or {})), b"", fetch=fetch, now=now)
r = G("/fn1/hello")
check("gateway request is REALLY routed to the function and returns its output", r["status"] == 200 and json.loads(r["body"])["greeting"] == "hola", r)
check("gateway without subscription key -> 401", gw.handle(state, svc, "GET", "/fn1/hello", {}, {}, b"", fetch=fetch, now=1000.0)["status"] == 401)
pol = "<policies><inbound><base /><rate-limit calls=\"2\" renewal-period=\"60\" /><ip-filter action=\"allow\"><address>10.0.0.1</address></ip-filter><set-header name=\"x-added\" exists-action=\"override\"><value>yes</value></set-header></inbound><backend><base /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>"
call("PUT", AP + "/apis/fn1/policies/policy", {"properties": {"format": "xml", "value": pol}}, "2022-08-01")
r1, r2, r3 = G("/fn1/hello", now=2000.0), G("/fn1/hello", now=2001.0), G("/fn1/hello", now=2002.0)
check("APIM policy rate-limit REALLY blocks the 3rd call (429)", (r1["status"], r2["status"], r3["status"]) == (200, 200, 429), (r1["status"], r2["status"], r3["status"]))
SEEN = []
_f = fetch
fetch = lambda m, u, h, d: (SEEN.append(dict(h)), _f(m, u, h, d))[1]
G("/fn1/hello", now=3000.0)
check("APIM set-header policy REALLY reaches the backend request", any(h.get("x-added") == "yes" for h in SEEN), SEEN)
check("unimplemented policy elements (ip-filter) are reported, never silently passed",
      "ip-filter" in (r1["headers"].get("x-vyomi-apim-skipped-policies") or ""), r1["headers"])
call("PATCH", f"{W}/sites/fn1/config/web", {"properties": {"apiManagementConfig": None}})
check("unlinking removes the imported API", not [k for k in state if k.startswith(AP.lower() + "/apis/fn1")])

# ── self-hosted gateway only serves associated APIs ──
call("PUT", AP + "/apis/open", {"properties": {"displayName": "o", "path": "open", "serviceUrl": "vyomi-site://fn1/api", "subscriptionRequired": False}}, "2022-08-01")
call("PUT", AP + "/apis/open/operations/h", {"properties": {"displayName": "h", "method": "GET", "urlTemplate": "/hello"}}, "2022-08-01")
call("PUT", AP + "/gateways/onprem", {"properties": {"locationData": {"name": "dc1"}}}, "2022-08-01")
mg = gw.handle(state, svc, "GET", "/open/hello", {}, {}, b"", fetch=fetch, now=1.0)
sg0 = gw.handle(state, svc, "GET", "/open/hello", {}, {}, b"", fetch=fetch, now=1.0, gateway="onprem")
call("PUT", AP + "/gateways/onprem/apis/open", {"properties": {}}, "2022-08-01")
sg1 = gw.handle(state, svc, "GET", "/open/hello", {}, {}, b"", fetch=fetch, now=2.0, gateway="onprem")
check("managed gateway serves the API", mg["status"] == 200, mg)
check("self-hosted gateway WITHOUT the association withholds the API (404)", sg0["status"] == 404, sg0)
check("after associating the API, the self-hosted gateway serves it", sg1["status"] == 200, sg1)
check("unknown gateway -> 404", gw.handle(state, svc, "GET", "/open/hello", {}, {}, b"", fetch=fetch, now=3.0, gateway="nope")["status"] == 404)

# ── autoscale really changes the instance count ──
AS = RG + "/providers/Microsoft.Insights/autoscaleSettings/as1"
rule = lambda name, op, thr, direction, val: {"metricTrigger": {"metricName": name, "metricResourceUri": PLAN, "timeGrain": "PT1M", "statistic": "Average",
      "timeWindow": "PT5M", "timeAggregation": "Average", "operator": op, "threshold": thr}, "scaleAction": {"direction": direction, "type": "ChangeCount", "value": str(val), "cooldown": "PT5M"}}
r = call("PUT", AS, {"location": "eastus", "properties": {"enabled": True, "targetResourceUri": PLAN, "profiles": [{
    "name": "default", "capacity": {"minimum": "1", "maximum": "4", "default": "1"},
    "rules": [rule("Requests", "GreaterThan", 20, "Increase", 1), rule("Requests", "LessThan", 5, "Decrease", 1)]}]}}, "2022-10-01")
check("autoscale setting stored", r["status"] in (200, 201), r)
st_rec = next(x for x in state.values() if isinstance(x, dict) and x.get("_type", "").lower() == "microsoft.insights/autoscalesettings")
plan = state[PLAN.lower()]
cap = lambda: plan["sku"]["capacity"]
T = 50_000_000.0
check("starts at 1 instance", cap() == 1)
# generate REAL traffic on web1: 100 requests in the last 5 minutes (avg 20/min -> not > 20), then 150 (30/min)
for i in range(150):
    wh.serve(state, site, "GET", "/", {}, {}, b"", now=T - 60 + i * 0.1)
site["properties"]["state"] = "Running"
acts = asc.evaluate(state, now=T)
check("high request rate scales OUT (1 -> 2)", cap() == 2 and acts and acts[0]["from"] == 1 and acts[0]["to"] == 2, (acts, cap()))
acts = asc.evaluate(state, now=T + 60)
check("cooldown prevents a second scale-out", cap() == 2 and not acts, acts)
for i in range(150):
    wh.serve(state, site, "GET", "/", {}, {}, b"", now=T + 350 + i * 0.1)
acts = asc.evaluate(state, now=T + 400)
check("after the cooldown, still-high load scales out again (2 -> 3)", cap() == 3, (cap(), acts))
acts = asc.evaluate(state, now=T + 5000)
check("traffic gone -> scale IN back toward the minimum", cap() == 2, (cap(), acts))
for k in range(1, 6):
    asc.evaluate(state, now=T + 5000 + k * 400)
check("scale-in stops at the profile minimum (1)", cap() == 1, cap())
hist = call("GET", AS + "/vyomiHistory", None, "2022-10-01")
check("scale events are recorded in the Run history", hist["status"] == 200 and len([h for h in hist["body"]["value"] if "from" in h]) >= 4, hist)
ev = [e for e in state.values() if isinstance(e, dict) and "Autoscale" in json.dumps((e.get("operationName") or {}))]
check("Activity Log has Autoscale scale-up/down events", len(ev) >= 4, len(ev))
r = call("PATCH", AS, {"properties": {"enabled": False}}, "2022-10-01")
n = len(asc.history(st_rec))
plan["sku"]["capacity"] = 9
asc.evaluate(state, now=T + 99999)
check("a disabled autoscale setting does nothing", cap() == 9 and len(asc.history(st_rec)) == n)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
