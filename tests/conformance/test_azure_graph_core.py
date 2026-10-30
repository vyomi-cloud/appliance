"""Microsoft Graph core conformance — the Entra ID (Azure AD) peer of the Azure RBAC
and ARM conformance checks. Exercises users, groups (+members), app registrations
(+ auto-created service principal + password credentials), domains, administrative
units, organization, and the directory audit log over the native `/v1.0/...` wire.
"""
import json

try:
    from core import azure_graph_core as graph
except ImportError:  # pragma: no cover - Pyodide flat layout
    import azure_graph_core as graph  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or graph.GraphStore()

    def call(m, p, b=None):
        return graph.dispatch(s, m, p, {}, {}, json.dumps(b).encode() if b is not None else b"")

    def body(r):
        return json.loads(r.body) if r.body else {}

    # Users
    r = call("POST", "/v1.0/users", {"displayName": "Alice Example", "userPrincipalName": "alice@vyomilearn.onmicrosoft.com",
                                     "passwordProfile": {"forceChangePasswordNextSignIn": True}})
    _check("create user -> 201", r.status == 201)
    alice = body(r)
    _check("duplicate userPrincipalName rejected",
           call("POST", "/v1.0/users", {"displayName": "Dup", "userPrincipalName": "alice@vyomilearn.onmicrosoft.com"}).status == 409)
    _check("list users shows Alice", any(u["id"] == alice["id"] for u in body(call("GET", "/v1.0/users"))["value"]))
    _check("get user by id", body(call("GET", f"/v1.0/users/{alice['id']}"))["displayName"] == "Alice Example")
    _check("patch user", call("PATCH", f"/v1.0/users/{alice['id']}", {"jobTitle": "Engineer"}).status == 204)
    _check("patched field reads back", body(call("GET", f"/v1.0/users/{alice['id']}"))["jobTitle"] == "Engineer")

    # Groups + members
    g = body(call("POST", "/v1.0/groups", {"displayName": "Engineering", "mailNickname": "eng",
                                           "securityEnabled": True, "mailEnabled": False, "groupTypes": []}))
    _check("create group -> security group", g["securityEnabled"] is True and g["groupTypes"] == [])
    _check("add member via $ref",
           call("POST", f"/v1.0/groups/{g['id']}/members/$ref", {"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{alice['id']}"}).status == 204)
    members = body(call("GET", f"/v1.0/groups/{g['id']}/members"))["value"]
    _check("member listed on group", any(m["id"] == alice["id"] for m in members))
    memberof = body(call("GET", f"/v1.0/users/{alice['id']}/memberOf"))["value"]
    _check("memberOf reflects the group", any(mo["id"] == g["id"] for mo in memberof))
    _check("remove member", call("DELETE", f"/v1.0/groups/{g['id']}/members/{alice['id']}/$ref").status == 204)
    _check("member removed", alice["id"] not in {m["id"] for m in body(call("GET", f"/v1.0/groups/{g['id']}/members"))["value"]})

    # Applications (app registrations) auto-create a service principal (enterprise app)
    app = body(call("POST", "/v1.0/applications", {"displayName": "uic-app", "signInAudience": "AzureADMyOrg"}))
    _check("create application -> 201 with appId", bool(app.get("appId")))
    sps = body(call("GET", "/v1.0/servicePrincipals"))["value"]
    _check("app registration auto-creates a service principal", any(sp["appId"] == app["appId"] for sp in sps))
    secret = body(call("POST", f"/v1.0/applications/{app['id']}/addPassword", {"passwordCredential": {"displayName": "default"}}))
    _check("addPassword returns a one-time secretText", bool(secret.get("secretText")) and bool(secret.get("keyId")))
    _check("secret listed on the application", any(c["keyId"] == secret["keyId"] for c in body(call("GET", f"/v1.0/applications/{app['id']}"))["passwordCredentials"]))
    _check("removePassword", call("POST", f"/v1.0/applications/{app['id']}/removePassword", {"keyId": secret["keyId"]}).status == 204)
    _check("delete application removes its service principal",
           call("DELETE", f"/v1.0/applications/{app['id']}").status == 204
           and not any(sp["appId"] == app["appId"] for sp in body(call("GET", "/v1.0/servicePrincipals"))["value"]))

    # Domains
    _check("default domain seeded", body(call("GET", "/v1.0/domains"))["value"][0]["isInitial"] is True)
    d = body(call("POST", "/v1.0/domains", {"id": "uic-domain.com"}))
    _check("add custom domain", d["id"] == "uic-domain.com" and d["isVerified"] is False)
    _check("delete custom domain", call("DELETE", "/v1.0/domains/uic-domain.com").status == 204)
    _check("initial domain cannot be deleted", call("DELETE", f"/v1.0/domains/{graph.DEFAULT_DOMAIN}").status == 400)

    # Administrative units
    au = body(call("POST", "/v1.0/directory/administrativeUnits", {"displayName": "West Region"}))
    _check("create administrative unit", au["displayName"] == "West Region")
    _check("list administrative units", any(x["id"] == au["id"] for x in body(call("GET", "/v1.0/directory/administrativeUnits"))["value"]))
    _check("delete administrative unit", call("DELETE", f"/v1.0/directory/administrativeUnits/{au['id']}").status == 204)

    # Organization (tenant) — Properties page
    org = body(call("GET", "/v1.0/organization"))["value"][0]
    _check("organization seeded with default domain", org["verifiedDomains"][0]["name"] == graph.DEFAULT_DOMAIN)
    _check("patch organization", call("PATCH", f"/v1.0/organization/{org['id']}", {"displayName": "Contoso"}).status == 204)
    _check("organization name round-trips", body(call("GET", "/v1.0/organization"))["value"][0]["displayName"] == "Contoso")

    # Directory audit log — every mutation above should have appended an entry.
    audits = body(call("GET", "/v1.0/auditLogs/directoryAudits"))["value"]
    _check("directory audit log recorded the mutations", len(audits) >= 8)
    _check("sign-in logs are honestly empty (no sign-in flow simulated)", body(call("GET", "/v1.0/auditLogs/signIns"))["value"] == [])

    print("\nMicrosoft Graph core conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
