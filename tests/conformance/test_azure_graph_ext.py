"""Entra extensions: licenses, Conditional Access engine (+ROPC enforcement), custom security attributes, BitLocker escrow,
AU members, per-user MFA, $batch.  Run: PYTHONPATH=. python tests/conformance/test_azure_graph_ext.py"""
import json
from urllib.parse import urlencode
from core import azure_graph_core as g
from core import azure_graph_ext_core as ext


def check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


st = g.GraphStore()
def call(m, p, b=None, q=None):
    r = g.dispatch(st, m, p, q or {}, {}, json.dumps(b).encode() if b is not None else b"")
    return r.status, (json.loads(r.body) if r.body else None)
def user(n, **kw):
    return call("POST", "/v1.0/users", {"displayName": n, "userPrincipalName": f"{n}@vyomilearn.onmicrosoft.com", "passwordProfile": {"password": "Pw-123456!", "forceChangePasswordNextSignIn": False}, **kw})[1]
def token(upn, app="app-1"):
    r = g.dispatch(st, "POST", "/x/oauth2/v2.0/token", {}, {}, urlencode({"grant_type": "password", "username": upn, "password": "Pw-123456!", "client_id": app}).encode())
    return r.status, json.loads(r.body)

# licenses
alice, bob = user("alice"), user("bob", usageLocation="US")
skus = call("GET", "/v1.0/subscribedSkus")[1]["value"]
p1 = next(s for s in skus if s["skuPartNumber"] == "AAD_PREMIUM")
check("sku has prepaid units and 0 consumed", p1["prepaidUnits"]["enabled"] == 100 and p1["consumedUnits"] == 0)
check("assign without usageLocation fails", call("POST", f"/v1.0/users/{alice['id']}/assignLicense", {"addLicenses": [{"skuId": p1["skuId"]}], "removeLicenses": []})[0] == 400)
check("assign ok", call("POST", f"/v1.0/users/{bob['id']}/assignLicense", {"addLicenses": [{"skuId": p1["skuId"]}], "removeLicenses": []})[0] == 200)
check("consumedUnits computed from assignments", next(s for s in call("GET", "/v1.0/subscribedSkus")[1]["value"] if s["skuId"] == p1["skuId"])["consumedUnits"] == 1)
check("licenseDetails", call("GET", f"/v1.0/users/{bob['id']}/licenseDetails")[1]["value"][0]["skuPartNumber"] == "AAD_PREMIUM")
ext.SKUS[2]["prepaid"] = 1
cs = call("POST", f"/v1.0/users/{bob['id']}/assignLicense", {"addLicenses": [{"skuId": ext.SKUS[2]["skuId"]}]})
carl = user("carl", usageLocation="US")
check("no free units -> 400", call("POST", f"/v1.0/users/{carl['id']}/assignLicense", {"addLicenses": [{"skuId": ext.SKUS[2]["skuId"]}]})[0] == 400)
ext.SKUS[2]["prepaid"] = 50
check("remove frees unit", call("POST", f"/v1.0/users/{bob['id']}/assignLicense", {"addLicenses": [], "removeLicenses": [p1["skuId"]]})[0] == 200
      and next(s for s in call("GET", "/v1.0/subscribedSkus")[1]["value"] if s["skuId"] == p1["skuId"])["consumedUnits"] == 0)

# conditional access
check("no policy -> token issued", token(alice["userPrincipalName"])[0] == 200)
loc = call("POST", "/v1.0/identity/conditionalAccess/namedLocations", {"displayName": "HQ", "isTrusted": True, "ipRanges": [{"@odata.type": "#microsoft.graph.iPv4CidrRange", "cidrAddress": "10.0.0.0/8"}]})[1]
check("bad CIDR rejected", call("POST", "/v1.0/identity/conditionalAccess/namedLocations", {"displayName": "x", "ipRanges": [{"cidrAddress": "nope"}]})[0] == 400)
pol = call("POST", "/v1.0/identity/conditionalAccess/policies", {"displayName": "Block outside HQ", "state": "enabled", "conditions": {
    "users": {"includeUsers": [alice["id"]]}, "applications": {"includeApplications": ["All"]},
    "locations": {"includeLocations": ["All"], "excludeLocations": [loc["id"]]}}, "grantControls": {"operator": "OR", "builtInControls": ["block"]}})
check("policy created", pol[0] == 201)
wi = lambda **k: call("POST", "/v1.0/identity/conditionalAccess/evaluate", {"userId": alice["id"], **k})[1]
check("what-if from outside HQ -> block", wi(ipAddress="8.8.8.8")["result"] == "block")
check("what-if from HQ -> allow (excluded location)", wi(ipAddress="10.1.2.3")["result"] == "allow")
check("other user unaffected", call("POST", "/v1.0/identity/conditionalAccess/evaluate", {"userId": bob["id"], "ipAddress": "8.8.8.8"})[1]["result"] == "allow")
s, b = token(alice["userPrincipalName"])
check("ROPC enforced: AADSTS53003", s == 403 and "AADSTS53003" in b["error_description"])
check("sign-in log shows CA failure", st.sign_in_logs[0]["conditionalAccessStatus"] == "failure" and st.sign_in_logs[0]["status"]["errorCode"] == 53003)
call("PATCH", f"/v1.0/identity/conditionalAccess/policies/{pol[1]['id']}", {"state": "enabledForReportingButNotEnforced"})
check("report-only does not block", token(alice["userPrincipalName"])[0] == 200 and wi(ipAddress="8.8.8.8")["policies"][0]["reportOnly"])
call("PATCH", f"/v1.0/identity/conditionalAccess/policies/{pol[1]['id']}", {"state": "enabled", "grantControls": {"operator": "OR", "builtInControls": ["mfa"]}})
s, b = token(alice["userPrincipalName"])
check("mfa required -> AADSTS50076", s == 400 and "AADSTS50076" in b["error_description"])
check("block+mfa invalid", call("POST", "/v1.0/identity/conditionalAccess/policies", {"displayName": "x", "grantControls": {"builtInControls": ["block", "mfa"]}})[0] == 400)
check("location in use cannot be deleted", call("DELETE", f"/v1.0/identity/conditionalAccess/namedLocations/{loc['id']}")[0] == 400)
call("DELETE", f"/v1.0/identity/conditionalAccess/policies/{pol[1]['id']}")
check("policy deleted -> token ok", token(alice["userPrincipalName"])[0] == 200)

# per-user MFA
call("PATCH", f"/v1.0/users/{bob['id']}/authentication/requirements", {"perUserMfaState": "enforced"})
check("per-user MFA enforced blocks ROPC", "AADSTS50076" in token(bob["userPrincipalName"])[1]["error_description"])

# custom security attributes
check("set created", call("POST", "/v1.0/directory/attributeSets", {"id": "Eng", "description": "d", "maxAttributesPerSet": 2})[0] == 201)
check("def created", call("POST", "/v1.0/directory/customSecurityAttributeDefinitions", {"attributeSet": "Eng", "name": "Project", "type": "String", "isCollection": False, "usePreDefinedValuesOnly": True, "allowedValues": ["Baker", "Cascade"]})[0] == 201)
check("undefined attr rejected", call("PATCH", f"/v1.0/users/{alice['id']}", {"customSecurityAttributes": {"Eng": {"Nope": "x"}}})[0] == 400)
check("disallowed value rejected", call("PATCH", f"/v1.0/users/{alice['id']}", {"customSecurityAttributes": {"Eng": {"Project": "Zed"}}})[0] == 400)
check("assign ok", call("PATCH", f"/v1.0/users/{alice['id']}", {"customSecurityAttributes": {"Eng": {"@odata.type": "#microsoft.graph.customSecurityAttributeValue", "Project": "Baker"}}})[0] == 204)
check("readable via $select only", call("GET", f"/v1.0/users/{alice['id']}", q={"$select": "customSecurityAttributes"})[1]["customSecurityAttributes"]["Eng"]["Project"] == "Baker"
      and "customSecurityAttributes" not in call("GET", f"/v1.0/users/{alice['id']}")[1])

# BitLocker
dev = call("POST", f"/v1.0/users/{alice['id']}/registeredDevices", {"displayName": "LAPTOP-1", "operatingSystem": "Windows"})[1]
check("escrow unknown device 404", call("POST", "/v1.0/informationProtection/bitlocker/recoveryKeys", {"deviceId": "nope"})[0] == 404)
k = call("POST", "/v1.0/informationProtection/bitlocker/recoveryKeys", {"deviceObjectId": dev["id"]})[1]
check("list hides key", "key" not in call("GET", "/v1.0/informationProtection/bitlocker/recoveryKeys", q={"$filter": f"deviceId eq '{dev['deviceId']}'"})[1]["value"][0])
n = len(st.audit_logs)
full = call("GET", f"/v1.0/informationProtection/bitlocker/recoveryKeys/{k['id']}", q={"$select": "key"})[1]
check("key is real recovery-password format", ext.valid_recovery_password(full["key"]) and len(full["key"].replace("-", "")) == 48)
check("reading the key is audited", len(st.audit_logs) == n + 1 and st.audit_logs[0]["activityDisplayName"] == "Read BitLocker key")
check("bad key rejected", call("POST", "/v1.0/informationProtection/bitlocker/recoveryKeys", {"deviceObjectId": dev["id"], "key": "123"})[0] == 400)

# AU members
au = call("POST", "/v1.0/directory/administrativeUnits", {"displayName": "EMEA"})[1]
check("add member", call("POST", f"/v1.0/directory/administrativeUnits/{au['id']}/members/$ref", {"@odata.id": f"https://graph.microsoft.com/v1.0/users/{alice['id']}"})[0] == 204)
check("list members", [m["displayName"] for m in call("GET", f"/v1.0/directory/administrativeUnits/{au['id']}/members")[1]["value"]] == ["alice"])
call("DELETE", f"/v1.0/directory/administrativeUnits/{au['id']}/members/{alice['id']}/$ref")
check("remove member", call("GET", f"/v1.0/directory/administrativeUnits/{au['id']}/members")[1]["value"] == [])

# $batch
b = call("POST", "/v1.0/$batch", {"requests": [{"id": "1", "method": "POST", "url": "/users", "body": {"displayName": "z1", "userPrincipalName": "z1@vyomilearn.onmicrosoft.com"}},
                                               {"id": "2", "method": "POST", "url": "/users", "body": {"displayName": "z1", "userPrincipalName": "z1@vyomilearn.onmicrosoft.com"}}]})[1]
check("batch: one created, duplicate 409", [r["status"] for r in b["responses"]] == [201, 409])
print("PASS")
