"""GCP Marketplace (Vyomi SaaS spaces), Cloud Hub and Privacy & Security — real, derived from live state.
Run: PYTHONPATH=. python tests/conformance/test_gcp_hub_core.py"""
import json

from core.aws_wire_router import AwsWireRouter
AwsWireRouter.STRICT_GCP_PROJECT = False   # engine conformance uses ad-hoc project ids (main's one-project-per-space rule is exercised elsewhere)

P = "demo"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    r = AwsWireRouter()

    def call(method, path, body=None, query=None):
        out = r.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
        return out["status"], json.loads(out["body"] or b"{}")

    B = f"/vyomi/gcp/{P}/marketplace"
    s, c = call("GET", f"{B}/products")
    _check("catalog lists the Vyomi SaaS spaces + categories", s == 200 and c["totalSize"] == 6 and "Payments" in c["categories"])
    _check("search by text", [p["id"] for p in call("GET", f"{B}/products", query={"q": "sms"})[1]["products"]] == ["vyomi-sms"])
    _check("filter by category", len(call("GET", f"{B}/products", query={"category": "Messaging"})[1]["products"]) == 2)
    _check("unknown product 404", call("GET", f"{B}/products/zzz")[0] == 404)
    _check("EULA required", call("POST", f"{B}/subscriptions", {"productId": "vyomi-pay"})[0] == 400)
    _check("unknown product subscribe 404", call("POST", f"{B}/subscriptions", {"productId": "nope", "acceptEula": True})[0] == 404)
    s, sub = call("POST", f"{B}/subscriptions", {"productId": "vyomi-pay", "acceptEula": True})
    _check("subscribe creates a live space", s == 200 and sub["space"]["endpoint"].endswith("vyomi-pay.spaces.vyomi.local") and sub["space"]["apiKey"].startswith("vy_"))
    _check("double subscribe 409", call("POST", f"{B}/subscriptions", {"productId": "vyomi-pay", "acceptEula": True})[0] == 409)
    _check("product shows its subscription", call("GET", f"{B}/products/vyomi-pay")[1]["subscription"]["id"] == sub["id"])
    _check("subscription is project-scoped", call("GET", f"/vyomi/gcp/other/marketplace/subscriptions")[1]["subscriptions"] == [])
    _check("cancel", call("DELETE", f"{B}/subscriptions/{sub['id']}")[1]["state"] == "CANCELLED" and call("DELETE", f"{B}/subscriptions/{sub['id']}")[0] == 404)

    # Cloud Hub aggregates REAL resources
    call("POST", "/storage/v1/b", {"name": "hub-b1"}, {"project": P})
    call("POST", "/storage/v1/b", {"name": "hub-b2"}, {"project": P})
    call("POST", f"/v1/projects/{P}/locations/global/keyRings", {}, {"keyRingId": "kr"})
    call("POST", f"/v1/projects/{P}/locations/global/keyRings/kr/cryptoKeys", {}, {"cryptoKeyId": "k1"})
    s, h = call("GET", f"/vyomi/gcp/{P}/hub/overview")
    counts = {x["product"]: x["count"] for x in h["resources"]}
    _check("hub counts real buckets and keys", counts.get("Cloud Storage buckets") == 2 and counts.get("Cloud KMS keys") == 1 and h["totalResources"] >= 3)
    _check("hub recent activity derives from audit logs", any(a["method"].endswith("CreateKeyRing") for a in h["recentActivity"]))
    call("DELETE", "/storage/v1/b/hub-b2")
    counts = {x["product"]: x["count"] for x in call("GET", f"/vyomi/gcp/{P}/hub/overview")[1]["resources"]}
    _check("hub follows deletes", counts.get("Cloud Storage buckets") == 1)

    # Privacy & Security
    s, pv = call("GET", f"/vyomi/gcp/{P}/privacy/overview")
    _check("privacy overview counts CMEK keys + audit entries", pv["customerManagedKeys"] == 1 and pv["access"]["adminActivityEntries"] >= 3)
    _check("access transparency is honest about Google staff", "no cloud-provider staff" in pv["access"]["accessTransparency"]["note"])
    s, log = call("GET", f"/vyomi/gcp/{P}/privacy/access-log")
    _check("access log entries have principal/method/resource", log["totalSize"] >= 3 and all(e["principal"] and e["method"] and e["resource"] for e in log["entries"]))
    _check("access log filters by principal", call("GET", f"/vyomi/gcp/{P}/privacy/access-log", query={"principal": "nobody@x"})[1]["totalSize"] == 0)
    print("gcp hub core: all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
