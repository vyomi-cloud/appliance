"""Quota requests (enforced), management certificates (real X.509 parse), ownership transfer, partner info, free services,
cost saved + simulated invoices, Marketplace/SaaS subscriptions."""
import base64
import datetime
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S  # type: ignore


try:
    from core.azure_arm_core import AzureArm as _LaxArm
    _LaxArm.STRICT_SUBSCRIPTION = False   # engine test: ad-hoc subscription ids
except Exception:
    pass


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def _make_cert(days_valid=3650, offset_days=-1):
    """Build a minimal X.509 DER by hand (tbs only -- the walker never verifies signatures)."""
    def tlv(tag, body):
        n = len(body)
        hdr = bytes([n]) if n < 128 else bytes([0x81, n]) if n < 256 else bytes([0x82, n >> 8, n & 255])
        return bytes([tag]) + hdr + body
    def name(cn):
        return tlv(0x30, tlv(0x31, tlv(0x30, tlv(0x06, b"\x55\x04\x03") + tlv(0x0C, cn.encode()))))
    now = datetime.datetime.now(datetime.timezone.utc)
    t = lambda d: tlv(0x17, (now + datetime.timedelta(days=d)).strftime("%y%m%d%H%M%SZ").encode())
    tbs = tlv(0x30, tlv(0xA0, tlv(0x02, b"\x02")) + tlv(0x02, b"\x01\x02") + tlv(0x30, tlv(0x06, b"\x2a\x86\x48\xce\x3d\x04\x03\x02"))
              + name("issuer-ca") + tlv(0x30, t(offset_days) + t(offset_days + days_valid)) + name("vyomi-mgmt-cert")
              + tlv(0x30, tlv(0x30, tlv(0x06, b"\x2a")) + tlv(0x03, b"\x00\x01")))
    return base64.b64encode(tlv(0x30, tbs + tlv(0x30, tlv(0x06, b"\x2a")) + tlv(0x03, b"\x00\x01"))).decode()


def run():
    a = AzureArm()
    av = {"api-version": "2024-01-01"}
    h = lambda m, p, b=None, q=None: a.handle(m, p, dict(av, **(q or {})), b)
    sub = f"/subscriptions/{S}"
    h("PUT", f"{sub}/resourceGroups/r", {"location": "eastus"})
    # ── quota
    q = f"{sub}/providers/Microsoft.Compute/locations/eastus/providers/Microsoft.Quota/quotas"
    _check("quota list", any(x["name"] == "cores" for x in h("GET", q)["body"]["value"]))
    _check("limit below usage refused / non-int", h("PUT", f"{q}/cores", {"properties": {"limit": {"limitObjectType": "LimitValue", "value": "x"}}})["status"] == 400)
    _check("above hard cap", h("PUT", f"{q}/cores", {"properties": {"limit": {"limitObjectType": "LimitValue", "value": 999999}}})["status"] == 400)
    r = h("PUT", f"{q}/cores", {"properties": {"limit": {"limitObjectType": "LimitValue", "value": 300}}})
    _check("auto-approved up to 4x", r["status"] == 200 and h("GET", f"{q}/cores")["body"]["properties"]["limit"]["value"] == 300)
    ug = h("GET", f"{sub}/providers/Microsoft.Compute/locations/eastus/usages")["body"]["value"]
    _check("usages report the raised limit", next(u for u in ug if u["name"]["value"] == "cores")["limit"] == 300)
    r = h("PUT", f"{q}/virtualMachines", {"properties": {"limit": {"limitObjectType": "LimitValue", "value": 450}}})
    _check("above auto-approval fails w/ support message", r["status"] == 400 and "support request" in r["body"]["error"]["message"])
    _check("requests recorded", len(h("GET", f"{sub}/providers/Microsoft.Quota/quotaRequests")["body"]["value"]) == 2)
    # enforcement uses raised limit: lower cores limit then create vm
    h("PUT", f"{q}/cores", {"properties": {"limit": {"limitObjectType": "LimitValue", "value": 1}}})
    vm = h("PUT", f"{sub}/resourceGroups/r/providers/Microsoft.Compute/virtualMachines/v1", {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_D4s_v3"}}})
    _check("enforcement reads the overridden limit", vm["status"] == 403 and "QuotaExceeded" in str(vm["body"]))
    # ── management certificates
    mc = f"{sub}/providers/Microsoft.Subscription/managementCertificates"
    _check("garbage cert", h("POST", mc, {"certificate": "AAAA"})["status"] == 400)
    der = _make_cert()
    r = h("POST", mc, {"certificate": der})
    _check("parse cert", r["status"] == 201 and r["body"]["properties"]["subject"] == "vyomi-mgmt-cert" and r["body"]["properties"]["issuer"] == "issuer-ca" and len(r["body"]["name"]) == 40)
    _check("duplicate", h("POST", mc, {"certificate": der})["status"] == 409)
    _check("expired", h("POST", mc, {"certificate": _make_cert(days_valid=10, offset_days=-100)})["status"] == 400)
    _check("delete cert", h("DELETE", f"{mc}/{r['body']['name']}")["status"] == 200 and h("GET", mc)["body"]["value"] == [])
    # ── ownership transfer
    tr = f"{sub}/providers/Microsoft.Billing/transferRequests"
    _check("bad recipient", h("POST", tr, {"recipientEmail": "nope"})["status"] == 400)
    owner = h("GET", f"{sub}/providers/Microsoft.Billing/billingProperties")["body"]["accountAdmin"]
    _check("cannot transfer to self", h("POST", tr, {"recipientEmail": owner})["status"] == 400)
    t1 = h("POST", tr, {"recipientEmail": "new.owner@example.com"})
    _check("transfer pending", t1["status"] == 201 and t1["body"]["properties"]["status"] == "Pending")
    _check("second pending refused", h("POST", tr, {"recipientEmail": "x@example.com"})["status"] == 409)
    _check("accept changes owner", h("POST", f"{tr}/{t1['body']['name']}/accept")["body"]["properties"]["status"] == "Completed"
           and h("GET", f"{sub}/providers/Microsoft.Billing/billingProperties")["body"]["accountAdmin"] == "new.owner@example.com")
    _check("cannot act twice", h("POST", f"{tr}/{t1['body']['name']}/decline")["status"] == 409)
    # ── partner
    pr = f"{sub}/providers/Microsoft.ManagementPartner/partners"
    _check("MPN digits only", h("PUT", f"{pr}/abc", {})["status"] == 400)
    _check("associate", h("PUT", f"{pr}/1234567", {"properties": {"partnerName": "Contoso"}})["status"] == 201)
    _check("one per tenant", h("PUT", f"{pr}/7654321", {})["status"] == 409)
    _check("update keeps version++", h("PUT", f"{pr}/1234567", {"properties": {"partnerName": "Contoso 2"}})["body"]["properties"]["version"] == 2)
    _check("remove", h("DELETE", f"{pr}/1234567")["status"] == 200 and h("GET", pr)["body"]["value"] == [])
    # ── free services + cost saved + invoices
    h("PUT", f"{sub}/resourceGroups/r/providers/Microsoft.Compute/virtualMachines/free1", {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}}})
    h("PUT", f"{q}/cores", {"properties": {"limit": {"limitObjectType": "LimitValue", "value": 100}}})
    fr = h("GET", f"{sub}/providers/Microsoft.Billing/freeServices")["body"]["value"]
    vmrow = next(x for x in fr if x["id"] == "vm-b1s")
    _check("free services measured + sorted by usage", vmrow["measured"] and vmrow["used"] >= 0 and [x["percentUsed"] for x in fr] == sorted((x["percentUsed"] for x in fr), reverse=True))
    h("PUT", f"{sub}/resourceGroups/r/providers/Microsoft.Compute/virtualMachines/big", {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_D2s_v3"}}})
    cs = h("GET", f"{sub}/providers/Microsoft.Billing/costSaved")["body"]
    _check("cost saved reflects inventory", cs["resourceCount"] >= 1 and cs["monthlyRunRate"] > 0 and cs["actualSpend"] == 0.0 and cs["annualizedSavings"] == round(cs["monthlyRunRate"] * 12, 2))
    inv = h("GET", f"{sub}/providers/Microsoft.Billing/invoices")["body"]["value"]
    _check("invoices simulated, nothing due", inv and inv[0]["properties"]["simulated"] and inv[0]["properties"]["amountDue"]["value"] == 0.0 and inv[0]["properties"]["status"] == "InProgress")
    _check("invoice detail", h("GET", f"{sub}/providers/Microsoft.Billing/invoices/{inv[0]['name']}")["status"] == 200)
    # ── marketplace
    off = h("GET", f"{sub}/providers/Microsoft.Marketplace/offers")["body"]["value"]
    _check("catalog", len(off) >= 8 and all(o["publisherId"] == "vyomi" for o in off))
    _check("category filter", all(o["category"] == "Messaging" for o in h("GET", f"{sub}/providers/Microsoft.Marketplace/offers", None, {"category": "Messaging"})["body"]["value"]))
    sp = f"{sub}/resourceGroups/r/providers/Microsoft.SaaS/resources"
    _check("unknown offer", h("PUT", f"{sp}/s1", {"properties": {"offerId": "nope", "planId": "x"}})["status"] == 400)
    _check("unknown plan", h("PUT", f"{sp}/s1", {"properties": {"offerId": "vyomi-stripe-space", "planId": "gold"}})["status"] == 400)
    r = h("PUT", f"{sp}/s1", {"location": "global", "properties": {"offerId": "vyomi-stripe-space", "planId": "sandbox"}})
    _check("subscribe", r["status"] == 201 and r["body"]["properties"]["status"] == "Subscribed" and r["body"]["properties"]["billingStatus"] == "Free")
    _check("duplicate offer in RG", h("PUT", f"{sp}/s2", {"properties": {"offerId": "vyomi-stripe-space", "planId": "team"}})["status"] == 409)
    _check("plan change", h("PATCH", f"{sp}/s1", {"properties": {"planId": "team"}})["body"]["properties"]["planId"] == "team")
    k1 = h("POST", f"{sp}/s1/listAccessInfo")["body"]["accessKey"]
    _check("key rotates", h("POST", f"{sp}/s1/regenerateAccessKey")["body"]["accessKey"] != k1)
    _check("unsubscribe", h("DELETE", f"{sp}/s1")["status"] == 200 and h("GET", f"{sp}/s1")["status"] == 404)
    print("PASS test_azure_billing_ext_core")


if __name__ == "__main__":
    run()
