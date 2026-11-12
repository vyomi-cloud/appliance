"""Network enforcement beyond storage/SQL/Cosmos: Service Bus network rule sets, Azure AI services (Azure OpenAI data
plane) networkAcls/publicNetworkAccess, Log Analytics public access for ingestion/query. A BLOCKED request is
actually refused (403); an ALLOWED one passes. The caller is a declared simulated client (x-vyomi-source-* headers,
or the same names as query parameters on ARM-proxied data planes).
Run: PYTHONPATH=. python tests/conformance/test_azure_netenforce.py"""
import json

from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
from core import azure_servicebus_core as sb

AzureArm.STRICT_SUBSCRIPTION = False
RG = f"/subscriptions/{SUB}/resourceGroups/ne-rg"
V = {"api-version": "2024-05-01"}
a = AzureArm()
put = lambda path, body, q=V: a.handle("PUT", path, dict(q), body)
post = lambda path, body, q=V: a.handle("POST", path, dict(q), body)


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


put(RG, {"location": "eastus"}, {"api-version": "2021-04-01"})
VN = f"{RG}/providers/Microsoft.Network/virtualNetworks/vn"
SN = f"{VN}/subnets/app"
r = put(VN, {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}, "subnets": [
    {"name": "app", "properties": {"addressPrefix": "10.0.1.0/24", "serviceEndpoints": [{"service": "Microsoft.ServiceBus"}, {"service": "Microsoft.CognitiveServices"}]}},
    {"name": "bare", "properties": {"addressPrefix": "10.0.2.0/24"}}]}}, {"api-version": "2023-09-01"})
ok("vnet created", r["status"] in (200, 201), r)

# ── Service Bus (Premium) ────────────────────────────────────────────────────────────────
NS = f"{RG}/providers/Microsoft.ServiceBus/namespaces/nsp"
r = put(NS, {"location": "eastus", "sku": {"name": "Premium", "tier": "Premium", "capacity": 1}}, {"api-version": "2022-10-01-preview"})
ok("premium namespace", r["status"] in (200, 201), r)
r = put(NS + "/networkRuleSets/default", {"properties": {"publicNetworkAccess": "Enabled", "defaultAction": "Deny", "trustedServiceAccessEnabled": True,
        "ipRules": [{"ipMask": "203.0.113.0/24", "action": "Allow"}], "virtualNetworkRules": [{"subnet": {"id": SN}}]}}, {"api-version": "2022-10-01-preview"})
ok("network rule set stored", r["status"] in (200, 201), r)
st = sb.MessagingStore() if hasattr(sb, "MessagingStore") else None
from core.aws_wire_router import InMemoryMessagingStore  # noqa: E402
st = InMemoryMessagingStore()
sbd = lambda **h: sb.dispatch(st, "PUT", "/q1", {}, {"x-vyomi-namespace": "nsp", **h}, b"", arm_state=a.state)
ok("SB: undeclared caller keeps legacy behaviour", sbd().status in (200, 201), sbd().body)
ok("SB: allowed IP passes", sbd(**{"x-vyomi-source-ip": "203.0.113.7"}).status in (200, 201))
b = sbd(**{"x-vyomi-source-ip": "192.0.2.9"})
ok("SB: IP outside ipRules BLOCKED 403", b.status == 403, b.status)
ok("SB: vnet rule + Microsoft.ServiceBus endpoint passes", sbd(**{"x-vyomi-source-subnet": SN}).status in (200, 201))
ok("SB: subnet without rule BLOCKED", sbd(**{"x-vyomi-source-subnet": VN + "/subnets/bare"}).status == 403)
ok("SB: trusted service passes", sbd(**{"x-vyomi-trusted-service": "1", "x-vyomi-source-ip": "192.0.2.9"}).status in (200, 201))
put(NS + "/networkRuleSets/default", {"properties": {"publicNetworkAccess": "Disabled", "defaultAction": "Allow"}}, {"api-version": "2022-10-01-preview"})
ok("SB: public access Disabled BLOCKS even an allowed IP", sbd(**{"x-vyomi-source-ip": "203.0.113.7"}).status == 403)
ok("SB: other namespaces unaffected", sb.dispatch(st, "GET", "/q1", {}, {"x-vyomi-namespace": "other"}, b"", arm_state=a.state).status == 200)

# ── Azure AI services / Azure OpenAI ─────────────────────────────────────────────────────
from core import ai_models_core as aim  # noqa: E402
CS = f"{RG}/providers/Microsoft.CognitiveServices/accounts/oai"
r = put(CS, {"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {"customSubDomainName": "oai"}}, {"api-version": "2024-10-01"})
ok("openai account", r["status"] in (200, 201), r)
r = put(CS + "/deployments/gpt", {"sku": {"name": "Standard", "capacity": 10}, "properties": {"model": {"format": "OpenAI", "name": "gpt-4o-mini", "version": "2024-07-18"}}}, {"api-version": "2024-10-01"})
ok("deployment", r["status"] in (200, 201, 202), r)
acct = a.state[CS.lower()]
acct["properties"]["networkAcls"] = {"defaultAction": "Deny", "ipRules": [{"value": "198.51.100.0/24"}], "virtualNetworkRules": [{"id": SN}]}
chat = lambda **h: aim.azure_openai_dispatch(a.state, "POST", "/openai/deployments/gpt/chat/completions", {}, {"api-key": "k", **h},
                                             json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode())
ok("AI: IP outside the allow-list BLOCKED 403", chat(**{"x-vyomi-source-ip": "192.0.2.1"})["status"] == 403)
ok("AI: allowed IP passes the firewall (not 403)", chat(**{"x-vyomi-source-ip": "198.51.100.5"})["status"] != 403)
ok("AI: vnet rule + Microsoft.CognitiveServices endpoint passes", chat(**{"x-vyomi-source-subnet": SN})["status"] != 403)
ok("AI: subnet w/o rule BLOCKED", chat(**{"x-vyomi-source-subnet": VN + "/subnets/bare"})["status"] == 403)
acct["properties"]["publicNetworkAccess"] = "Disabled"
ok("AI: public access Disabled BLOCKS an undeclared caller", chat()["status"] == 403)
PE = f"{RG}/providers/Microsoft.Network/privateEndpoints/pe"
a.state[PE.lower()] = {"id": PE, "_type": "microsoft.network/privateendpoints", "properties": {"privateLinkServiceConnections": [
    {"properties": {"privateLinkServiceId": CS, "privateLinkServiceConnectionState": {"status": "Approved"}}}]}}
ok("AI: approved private endpoint passes", chat(**{"x-vyomi-private-endpoint": PE})["status"] != 403)
# ARM-proxied inference path (Nano): the declaration rides as query parameters
r = a.handle("POST", CS + "/openai/deployments/gpt/chat/completions", {"api-version": "2024-10-01"}, {"messages": [{"role": "user", "content": "hi"}]})
ok("AI: ARM-proxied inference BLOCKED while public access is Disabled", r["status"] == 403, r)
r = a.handle("POST", CS + "/openai/deployments/gpt/chat/completions", {"api-version": "2024-10-01", "x-vyomi-private-endpoint": PE}, {"messages": [{"role": "user", "content": "hi"}]})
ok("AI: ARM-proxied inference via the private endpoint is not firewall-blocked", r["status"] != 403, r)

# ── Log Analytics ────────────────────────────────────────────────────────────────────────
WS = f"{RG}/providers/Microsoft.OperationalInsights/workspaces/law-ne"
r = put(WS, {"location": "eastus", "properties": {"publicNetworkAccessForIngestion": "Enabled", "publicNetworkAccessForQuery": "Disabled"}}, {"api-version": "2022-10-01"})
ok("workspace", r["status"] in (200, 201), r)
ing = lambda **q: a.handle("POST", WS + "/api/logs", {"api-version": "2022-10-01", "logType": "App", **q}, [{"a": 1}])
qry = lambda **q: a.handle("POST", WS + "/api/query", {"api-version": "2022-10-01", **q}, {"query": "App_CL | take 1"})
ok("LA: ingestion allowed while ingestion access Enabled", ing()["status"] < 300, ing())
ok("LA: query BLOCKED while query access Disabled", qry()["status"] == 403, qry())
put(WS, {"location": "eastus", "properties": {"publicNetworkAccessForIngestion": "Disabled", "publicNetworkAccessForQuery": "Enabled"}}, {"api-version": "2022-10-01"})
ok("LA: ingestion BLOCKED once ingestion access Disabled", ing()["status"] == 403)
ok("LA: query allowed once query access Enabled", qry()["status"] < 300, qry())
a.state[PE.lower()]["properties"]["privateLinkServiceConnections"][0]["properties"]["privateLinkServiceId"] = WS
ok("LA: private endpoint path reaches a locked-down workspace", ing(**{"x-vyomi-private-endpoint": PE})["status"] < 300)
# ── Cosmos DB CORS ───────────────────────────────────────────────────────────────────────
from core import azure_cosmos_core as cz  # noqa: E402
CA = f"{RG}/providers/Microsoft.DocumentDB/databaseAccounts/cz1"
r = put(CA, {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {"databaseAccountOfferType": "Standard",
        "locations": [{"locationName": "East US", "failoverPriority": 0}],
        "cors": [{"allowedOrigins": "https://app.contoso.com,https://*.fabrikam.com", "allowedMethods": "GET,POST", "allowedHeaders": "x-ms-version,content-type", "exposedHeaders": "x-ms-request-charge", "maxAgeInSeconds": 600}]}},
        {"api-version": "2024-05-15"})
ok("cosmos account with cors", r["status"] in (200, 201, 202), r)
cst = cz.CosmosStore()
cd = lambda m, h, p="/dbs", body=b"": cz.dispatch(cst, m, p, {}, {"x-vyomi-account": "cz1", **h}, body, arm_state=a.state)
pre = lambda o, m="GET", hh="x-ms-version": cd("OPTIONS", {"Origin": o, "Access-Control-Request-Method": m, "Access-Control-Request-Headers": hh})
r = pre("https://app.contoso.com")
ok("CORS preflight: listed origin allowed with ACAO + max-age", r.status == 200 and r.headers["access-control-allow-origin"] == "https://app.contoso.com" and r.headers["access-control-max-age"] == "600", r.headers)
ok("CORS preflight: *.domain wildcard origin allowed", pre("https://x.fabrikam.com").status == 200)
r = pre("https://evil.example")
ok("CORS preflight: unlisted origin BLOCKED (403, no ACAO)", r.status == 403 and "access-control-allow-origin" not in r.headers)
ok("CORS preflight: method outside allowedMethods BLOCKED", pre("https://app.contoso.com", "DELETE").status == 403)
ok("CORS preflight: header outside allowedHeaders BLOCKED", pre("https://app.contoso.com", "GET", "x-secret").status == 403)
r = cd("GET", {"Origin": "https://app.contoso.com"})
ok("actual request: ACAO + expose-headers on an admitted origin", r.status == 200 and r.headers.get("access-control-allow-origin") == "https://app.contoso.com" and r.headers.get("access-control-expose-headers") == "x-ms-request-charge", r.headers)
r = cd("GET", {"Origin": "https://evil.example"})
ok("actual request: no ACAO for an unlisted origin", "access-control-allow-origin" not in r.headers)
ok("no Origin: no CORS headers", "access-control-allow-origin" not in cd("GET", {}).headers)
print("netenforce ok")
