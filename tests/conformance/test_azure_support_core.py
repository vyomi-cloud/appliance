"""Azure support requests (Microsoft.Support) conformance — core/azure_support_core.py through the
ARM dispatcher. Run: PYTHONPATH=. python tests/conformance/test_azure_support_core.py"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
except ImportError:  # pragma: no cover - Pyodide flat layout
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore

AV = {"api-version": "2020-04-01"}
BASE = f"/subscriptions/{SUB}/providers/Microsoft.Support"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    arm = AzureArm()
    h = lambda m, p, b=None, q=None: arm.handle(m, p, q or AV, b)
    svcs = h("GET", f"{BASE}/services")["body"]["value"]
    _check("services listed with display names", len(svcs) > 10 and all(s["properties"]["displayName"] for s in svcs))
    sql = next(s for s in svcs if s["properties"]["displayName"] == "Azure SQL Database")
    pcs = h("GET", f"{sql['id'].replace('/providers/Microsoft.Support', BASE.split('/providers')[0] + '/providers/Microsoft.Support')}/problemClassifications")
    _check("problem classifications for a service", pcs["status"] == 200 and pcs["body"]["value"])
    pc = pcs["body"]["value"][0]["id"]
    bad = h("GET", f"{BASE}/services/nope/problemClassifications")
    _check("unknown service 404", bad["status"] == 404)

    chk = h("POST", f"{BASE}/checkNameAvailability", {"name": "t1", "type": "Microsoft.Support/supportTickets"})
    _check("name available", chk["body"]["nameAvailable"] is True)
    _check("invalid name rejected", h("POST", f"{BASE}/checkNameAvailability", {"name": "bad name!", "type": "Microsoft.Support/supportTickets"})["body"]["reason"] == "Invalid")

    contact = {"firstName": "A", "lastName": "B", "preferredContactMethod": "Email", "primaryEmailAddress": "a@b.co",
               "preferredTimeZone": "UTC", "country": "IND", "preferredSupportLanguage": "en-US"}
    body = {"properties": {"title": "DB slow", "description": "queries are slow", "severity": "Moderate",
                           "problemClassificationId": pc, "serviceId": sql["id"], "contactDetails": contact}}
    for field in ("title", "severity", "problemClassificationId"):
        b = {"properties": {k: v for k, v in body["properties"].items() if k != field}}
        _check(f"missing {field} -> 400", h("PUT", f"{BASE}/supportTickets/t1", b)["status"] == 400)
    b = {"properties": {**body["properties"], "severity": "Urgent"}}
    _check("bad severity -> 400", h("PUT", f"{BASE}/supportTickets/t1", b)["status"] == 400)
    b = {"properties": {**body["properties"], "problemClassificationId": svcs[0]["id"] + "/problemClassifications/x"}}
    _check("classification of another service -> 400", h("PUT", f"{BASE}/supportTickets/t1", b)["status"] == 400)
    b = {"properties": {**body["properties"], "technicalTicketDetails": {"resourceId": "/subscriptions/x/resourceGroups/r/providers/Microsoft.Sql/servers/none"}}}
    _check("unknown technical resource -> 400", h("PUT", f"{BASE}/supportTickets/t1", b)["status"] == 400)
    b = {"properties": {**body["properties"], "contactDetails": {**contact, "preferredContactMethod": "Phone"}}}
    _check("phone method needs number -> 400", h("PUT", f"{BASE}/supportTickets/t1", b)["status"] == 400)

    r = h("PUT", f"{BASE}/supportTickets/t1", body)
    p = r["body"]["properties"]
    _check("create ok, Open, Vyomi engineer + reference", r["status"] == 200 and p["status"] == "Open"
           and p["supportTicketId"].startswith("VYO-") and p["supportEngineer"]["emailAddress"] == "support@vyomi.cloud")
    _check("honest delivery marker", p["vyomiDelivery"] == "recorded-locally")
    _check("duplicate -> 409", h("PUT", f"{BASE}/supportTickets/t1", body)["status"] == 409)
    _check("name now taken", h("POST", f"{BASE}/checkNameAvailability", {"name": "t1", "type": "Microsoft.Support/supportTickets"})["body"]["reason"] == "AlreadyExists")
    _check("get", h("GET", f"{BASE}/supportTickets/t1")["body"]["name"] == "t1")
    _check("get missing 404", h("GET", f"{BASE}/supportTickets/zz")["status"] == 404)

    comms = h("GET", f"{BASE}/supportTickets/t1/communications")["body"]["value"]
    _check("acknowledgement communication from Vyomi Support", len(comms) == 1 and comms[0]["properties"]["sender"] == "Vyomi Support")
    _check("add reply needs subject/body", h("PUT", f"{BASE}/supportTickets/t1/communications/c1", {"properties": {}})["status"] == 400)
    _check("add reply", h("PUT", f"{BASE}/supportTickets/t1/communications/c1", {"properties": {"subject": "re", "body": "more info"}})["status"] == 200)
    _check("two communications", len(h("GET", f"{BASE}/supportTickets/t1/communications")["body"]["value"]) == 2)

    u = h("PATCH", f"{BASE}/supportTickets/t1", {"severity": "Critical"})
    _check("severity update", u["body"]["properties"]["severity"] == "Critical")
    _check("bad status", h("PATCH", f"{BASE}/supportTickets/t1", {"status": "Weird"})["status"] == 400)
    h("PUT", f"{BASE}/supportTickets/t2", body)
    _check("list has both", len(h("GET", f"{BASE}/supportTickets")["body"]["value"]) == 2)
    c = h("PATCH", f"{BASE}/supportTickets/t1", {"status": "Closed"})
    _check("close", c["body"]["properties"]["status"] == "Closed")
    _check("closed ticket cannot be edited", h("PATCH", f"{BASE}/supportTickets/t1", {"severity": "Minimal"})["status"] == 409)
    _check("closed ticket takes no replies", h("PUT", f"{BASE}/supportTickets/t1/communications/c2", {"properties": {"subject": "x", "body": "y"}})["status"] == 409)
    f = h("GET", f"{BASE}/supportTickets", q={**AV, "$filter": "Status eq 'Open'"})["body"]["value"]
    _check("$filter Status eq 'Open'", [t["name"] for t in f] == ["t2"])
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
