"""Managed-Kubernetes tier gate: AKS / GKE / EKS are Pro / Max / Enterprise ONLY.

Free and the legacy API-only tiers (nano, micro, lite) are COMPLETELY restricted; Pro gets only its
primary cloud's Kubernetes; Max / Enterprise get all three.  Proved at every layer a request can take:
  policy   core/tier_policy.py            (category "kubernetes", per-tier lists, check_service)
  cores    AzureArm.handle (create / list / runCommand-kubectl / Backup-for-AKS / Flux / nested template
           deployment), gcp_container_core.dispatch (create / list / kubectl data plane / Backup for GKE),
           AwsWireRouter.handle (all three clouds + EKS by SigV4 scope)
  http     the appliance middleware (resolve_provider_service + native-style 403) via a TestClient
  nano     arm_nano() fails CLOSED (Free) until set_tier() delivers the licence tier

Run:  CLOUDLEARN_TIER_ENFORCE=1 PYTHONPATH=. python3 tests/conformance/test_k8s_tier_gate.py
(Sections 1-5 run on Python 3.9; section 6 imports server.py, which needs Python >= 3.10, e.g. the s3_simulator .venv 3.14.)
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import k8s_tier_gate as G  # noqa: E402
from core import tier_policy as TP  # noqa: E402
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION  # noqa: E402
from core import gcp_container_core as gk  # noqa: E402

PASS = FAIL = 0
TIERS = ["free", "nano", "micro", "lite", "pro", "max", "enterprise"]
ALLOWED_ALL = {"max", "enterprise"}
CLOUDS = ["azure", "gcp", "aws"]


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail)[:200] if detail and not ok else ''}")


def allowed(tier, cloud, primary):
    if tier in ALLOWED_ALL:
        return True
    return tier == "pro" and primary == cloud


PRIMARIES = {"azure": "azure", "gcp": "gcp", "aws": "aws"}

# ── 1. policy table ──────────────────────────────────────────────────────────────────────────────
check("SERVICE_CATEGORY maps aks/gke/eks -> kubernetes",
      all(TP.SERVICE_CATEGORY.get(k) == "kubernetes" for k in ("aks", "gke", "eks")))
check("ALL_CATEGORIES / CONFORMANCE_NO_COMPUTE do not leak kubernetes",
      "kubernetes" not in TP.ALL_CATEGORIES and "kubernetes" not in TP.CONFORMANCE_NO_COMPUTE)
for t in ("free", "nano", "micro", "lite"):
    p = TP.policy_for(t)
    check(f"{t}: kubernetes not unlocked, listed locked",
          "kubernetes" not in (p["service_categories_unlocked"] if p["service_categories_unlocked"] != "ALL" else []) and
          p["service_categories_unlocked"] != "ALL" and "kubernetes" in p["service_categories_locked"], p["service_categories_unlocked"])
for t in ("pro", "max", "enterprise"):
    check(f"{t}: all categories (incl. kubernetes) unlocked", TP.policy_for(t)["service_categories_unlocked"] == "ALL")
for t in TIERS:
    for cloud, key in (("azure", "aks"), ("gcp", "gke"), ("aws", "eks")):
        for primary in ("azure", "gcp", "aws", ""):
            r = TP.check_service(t, key, primary_cloud=primary, request_cloud=cloud)
            want = allowed(t, cloud, primary)
            check(f"tier_policy.check_service {t:10s} {key} primary={primary or '-':5s} -> {'allow' if want else 'deny'}",
                  bool(r["ok"]) == want, r)
r = TP.check_service("free", "aks", request_cloud="azure")
check("denial names the required tiers", "Pro" in r["reason"] and "Max" in r["reason"] and r["upgrade_to"] == "pro", r)
check("legacy alias 'student' (-> pro) follows the Pro primary-cloud rule",
      TP.check_service("student", "gke", primary_cloud="gcp", request_cloud="gcp")["ok"]
      and not TP.check_service("student", "gke", primary_cloud="azure", request_cloud="gcp")["ok"])

# ── 2. cores ─────────────────────────────────────────────────────────────────────────────────────
SUB = DEFAULT_SUBSCRIPTION
AV = "2024-09-02-preview"
RG = f"/subscriptions/{SUB}/resourceGroups/k8s-rg"
AKS = f"{RG}/providers/Microsoft.ContainerService/managedClusters/k1"
VAULT = f"{RG}/providers/Microsoft.DataProtection/backupVaults/v1"
FLUX = f"{AKS}/providers/Microsoft.KubernetesConfiguration/fluxConfigurations/f1"
L = "/v1/projects/p1/locations/us-central1"
EKS_HDR = {"Authorization": "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20260101/us-east-1/eks/aws4_request, SignedHeaders=host, Signature=x"}


def status(r):
    return r["status"] if isinstance(r, dict) else r.status


def seed_unlocked():
    """A real AKS cluster + GKE cluster created while the gate is OFF (provider None)."""
    G.set_provider(None)
    arm = AzureArm()
    arm.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    arm.handle("PUT", AKS, {"api-version": AV}, {"location": "eastus"})
    st = gk.ContainerStore()
    gk.dispatch(st, "POST", L + "/clusters", {}, {}, json.dumps({"cluster": {"name": "c1", "initialNodeCount": 1}}).encode())
    return arm, st


def azure_routes(arm):
    return {
        "create":     lambda: arm.handle("PUT", AKS + "-new", {"api-version": AV}, {"location": "eastus"}),
        "list":       lambda: arm.handle("GET", f"{RG}/providers/Microsoft.ContainerService/managedClusters", {"api-version": AV}),
        "runCommand": lambda: arm.handle("POST", AKS + "/runCommand", {"api-version": AV}, {"command": "kubectl get ns"}),
        "backup":     lambda: arm.handle("PUT", VAULT, {"api-version": "2024-04-01"}, {"location": "eastus", "properties": {}}),
        "flux":       lambda: arm.handle("PUT", FLUX, {"api-version": "2023-05-01"}, {"properties": {}}),
        "template":   lambda: arm.handle("PUT", RG + "/providers/Microsoft.Resources/deployments/d1", {"api-version": "2021-04-01"},
                                          {"properties": {"mode": "Incremental", "template": {"$schema": "x", "contentVersion": "1.0.0.0", "resources": [
                                              {"type": "Microsoft.ContainerService/managedClusters", "apiVersion": AV, "name": "viaTpl", "location": "eastus", "properties": {}}]}}}),
    }


def gcp_routes(st):
    def d(m, p, b=None):
        return gk.dispatch(st, m, p, {}, {}, json.dumps(b).encode() if b is not None else b"")
    return {
        "create":     lambda: d("POST", L + "/clusters", {"cluster": {"name": "c2", "initialNodeCount": 1}}),
        "list":       lambda: d("GET", L + "/clusters"),
        "runCommand": lambda: d("GET", L + "/clusters/c1/k8s/api/v1/namespaces"),      # kubectl data plane
        "backup":     lambda: d("POST", L + "/backupPlans?backupPlanId=bp1", {"cluster": f"projects/p1/locations/us-central1/clusters/c1"}),
        "serverConfig": lambda: d("GET", L + "/serverConfig"),
    }


def is_denied(resp, cloud):
    s = status(resp)
    if isinstance(resp, dict) and str((resp.get("body") or {}).get("type", "")).lower() == "microsoft.resources/deployments":
        pr = resp["body"]["properties"]      # a template deployment answers 200 but its AKS resource must fail 403
        return pr.get("provisioningState") == "Failed" and "FeatureNotAvailableForTier" in json.dumps(pr.get("error"))
    if s != 403:
        return False
    body = resp["body"] if isinstance(resp, dict) else resp.body
    if isinstance(body, (bytes, bytearray)):
        body = json.loads(body or b"{}")
    if cloud == "azure":
        return body.get("error", {}).get("code") == "FeatureNotAvailableForTier"
    if cloud == "gcp":
        return body.get("error", {}).get("status") == "PERMISSION_DENIED"
    return body.get("__type") == "AccessDeniedException"


for tier in TIERS:
    for primary in ("azure", "gcp"):
        if tier != "pro" and primary == "gcp":
            continue                      # primary only matters for Pro
        arm, st = seed_unlocked()
        G.set_provider(lambda t=tier, p=primary: (t, p))
        for cloud, routes in (("azure", azure_routes(arm)), ("gcp", gcp_routes(st))):
            for route, fn in routes.items():
                r = fn()
                want = allowed(tier, cloud, primary)
                tag = f"core {tier:10s} primary={primary if tier == 'pro' else '-':5s} {cloud:5s} {route:12s}"
                if want:
                    check(tag + " -> allowed", not is_denied(r, cloud) and status(r) != 403, (status(r), r))
                else:
                    check(tag + " -> 403 native", is_denied(r, cloud), (status(r), r))
G.set_provider(None)

# the denial carries a message naming the required tier + upgrade fields (ARM / GCP shapes)
arm, st = seed_unlocked()
G.set_provider(lambda: ("free", ""))
r = azure_routes(arm)["create"]()
check("ARM denial: code FeatureNotAvailableForTier + message names Pro/Max/Enterprise",
      r["body"]["error"]["code"] == "FeatureNotAvailableForTier" and "Pro, Max or Enterprise" in r["body"]["error"]["message"], r)
r = gcp_routes(st)["create"]()
b = json.loads(r.body)
check("GCP denial: 403 PERMISSION_DENIED + ErrorInfo TIER_REQUIRED",
      r.status == 403 and b["error"]["status"] == "PERMISSION_DENIED" and b["error"]["details"][0]["reason"] == "TIER_REQUIRED", b)
G.set_provider(None)

# a locked tier leaves state untouched (nothing was created through any back door)
arm, st = seed_unlocked()
n_az = sum(1 for v in arm.state.values() if isinstance(v, dict) and str(v.get("_type", "")).lower() == "microsoft.containerservice/managedclusters")
G.set_provider(lambda: ("free", ""))
for fn in list(azure_routes(arm).values()):
    fn()
for fn in list(gcp_routes(st).values()):
    fn()
G.set_provider(None)
n_az2 = sum(1 for v in arm.state.values() if isinstance(v, dict) and str(v.get("_type", "")).lower() == "microsoft.containerservice/managedclusters")
check("Free: no AKS cluster created by any route (incl. template deployment)", n_az2 == n_az == 1, (n_az, n_az2))
check("Free: no GKE cluster created", len(st.clusters) == 1, list(st.clusters))
check("Free: no Backup-for-AKS vault / Flux config created",
      not any("dataprotection" in str(k) or "kubernetesconfiguration" in str(k) for k in arm.state))

# ── 3. the native-wire router (Nano + appliance wire ingress), all three clouds ──────────────────
from core.aws_wire_router import AwsWireRouter  # noqa: E402


def wire(router, cloud):
    if cloud == "azure":
        return router.handle("PUT", AKS + "-w", {"api-version": AV}, {}, json.dumps({"location": "eastus"}).encode())
    if cloud == "gcp":
        return router.handle("POST", L + "/clusters", {}, {}, json.dumps({"cluster": {"name": "cw", "initialNodeCount": 1}}).encode())
    return router.handle("POST", "/clusters", {}, dict(EKS_HDR, **{"content-type": "application/json"}), b'{"name":"e1"}')


for tier in TIERS:
    for cloud in CLOUDS:
        G.set_provider(lambda t=tier: (t, "azure"))
        router = AwsWireRouter()
        r = wire(router, cloud)
        want = allowed(tier, cloud, "azure")
        body = r["body"] if isinstance(r["body"], (bytes, bytearray)) else json.dumps(r["body"]).encode()
        if want:
            check(f"wire {tier:10s} {cloud:5s} create -> not tier-denied", r["status"] != 403 or b"Tier" not in body and b"tier" not in body, r)
        else:
            check(f"wire {tier:10s} {cloud:5s} create -> 403 native", r["status"] == 403 and
                  {"azure": b"FeatureNotAvailableForTier", "gcp": b"PERMISSION_DENIED", "aws": b"AccessDeniedException"}[cloud] in body, r)
G.set_provider(None)

# ── 4. Nano: arm_nano() fails closed; the licence tier opens it ──────────────────────────────────
check("unarmed + no provider -> not enforced (bare cores / unit tests)", G.check("azure") is None)
G._NANO.update(armed=False, tier="free", primary="")
G.arm_nano()
check("Nano armed with NO tier info -> fails closed (Free): AKS/GKE/EKS all denied", all(G.check(c) for c in CLOUDS))
G.set_tier("pro", "gcp")
check("Nano Pro/primary=gcp: GKE open, AKS+EKS locked", G.check("gcp") is None and G.check("azure") and G.check("aws"))
G.set_tier("max", "")
check("Nano Max: all three open", all(G.check(c) is None for c in CLOUDS))
G.set_tier("nano", "")
check("Nano tier 'nano': locked", all(G.check(c) for c in CLOUDS))
G.set_tier("garbage-tier", "")
check("Nano unknown tier string -> treated as Free (locked)", all(G.check(c) for c in CLOUDS))
G._NANO.update(armed=False, tier="free", primary="")

def _broken():
    raise RuntimeError("provider blew up")
G.set_provider(_broken)
check("a crashing tier provider fails CLOSED", all(G.check(c) for c in CLOUDS))
G.set_provider(None)

# ── 5. classifier covers every plane (no back door by path shape) ────────────────────────────────
for p, c in [(AKS, "azure"), (AKS + "/runCommand", "azure"), (AKS + "/agentPools/np1", "azure"), (VAULT + "/backupPolicies/p", "azure"),
             (FLUX, "azure"), (L + "/clusters", "gcp"), (L + "/clusters/c1/k8s/api/v1/pods", "gcp"), (L + "/backupPlans", "gcp"),
             ("/v1beta1/projects/p1/zones/z/clusters", "gcp"), ("/api/container/clusters", "gcp"), ("/api/sub/container/resize/c1", "gcp")]:
    check(f"classify {p[-48:]} -> {c}", G.classify(p) == c)
check("classify strips the console wire prefix (/_wire, /nano/_wire)",
      G.classify("/_wire" + L + "/clusters") == "gcp" and G.classify("/nano/_wire" + AKS + "/runCommand") == "azure")
check("classify EKS by SigV4 scope", G.classify("/clusters/x/node-groups", EKS_HDR) == "aws")
check("classify leaves non-k8s alone", all(G.classify(p) is None for p in (
    f"{RG}/providers/Microsoft.Compute/virtualMachines/vm1", "/storage/v1/b", L + "/operations", "/api/spaces")))

# ── 6. HTTP middleware (real server stack) ───────────────────────────────────────────────────────
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "1"
try:
    import asyncio
    import server as S

    class _Resp:
        def __init__(self, status_code, headers, body):
            self.status_code, self.text = status_code, body.decode("utf-8", "replace")
            self.headers = {k.lower(): v for k, v in headers.items()}

    def asgi(method, path, body=None, headers=None):
        """Drive the real FastAPI app (middleware stack included) in-process -- no httpx needed."""
        path, _, qs = path.partition("?")
        raw = json.dumps(body).encode() if body is not None else b""
        hdrs = [(b"host", b"testserver"), (b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]
        hdrs += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http", "path": path,
                 "raw_path": path.encode(), "query_string": qs.encode(), "headers": hdrs, "client": ("127.0.0.1", 1), "server": ("testserver", 80)}
        out = {"status": 500, "headers": {}, "body": b""}

        async def run():
            sent = {"done": False}

            async def receive():
                if not sent["done"]:
                    sent["done"] = True
                    return {"type": "http.request", "body": raw, "more_body": False}
                return {"type": "http.disconnect"}

            async def send(msg):
                if msg["type"] == "http.response.start":
                    out["status"] = msg["status"]
                    out["headers"] = {k.decode(): v.decode() for k, v in msg["headers"]}
                elif msg["type"] == "http.response.body":
                    out["body"] += msg.get("body", b"")
            await S.app(scope, receive, send)
        asyncio.run(run())
        return _Resp(out["status"], out["headers"], out["body"])

    def set_lic(tier, primary=""):
        S.STATE.setdefault("license", {})["tier"] = tier
        try:
            t = S._tenant_dict(S._active_tenant_id())
            t["primary_cloud"] = primary
            t["license_tier"] = tier
        except Exception:
            pass

    http_routes = {
        "azure": [("PUT", AKS + "-h?api-version=" + AV, {"location": "eastus"}), ("POST", AKS + "/runCommand?api-version=" + AV, {"command": "kubectl get ns"}),
                  ("PUT", VAULT + "?api-version=2024-04-01", {"location": "eastus", "properties": {}})],
        "gcp": [("POST", "/_wire" + L + "/clusters", {"cluster": {"name": "h0"}}), ("POST", L + "/clusters", {"cluster": {"name": "h1"}}), ("GET", L + "/clusters/c1/k8s/api/v1/namespaces", None),
                ("POST", "/api/container/clusters", {"name": "h2"})],
        "aws": [("POST", "/clusters", {"name": "e1"})],
    }
    for tier in ("free", "nano", "micro", "lite", "pro", "max"):
        for cloud, rs in http_routes.items():
            for m, path, body in rs:
                set_lic(tier, "azure")
                r = asgi(m, path, body, EKS_HDR if cloud == "aws" else {})
                want = allowed(tier, cloud, "azure")
                tag = f"http {tier:6s} {cloud:5s} {m:4s} {path.split('?')[0][-34:]}"
                if want:
                    check(tag + " -> not tier-denied", r.headers.get("x-cloudlearn-tier-denied") is None, (r.status_code, r.text[:150]))
                else:
                    code = {"azure": "FeatureNotAvailableForTier", "gcp": "PERMISSION_DENIED", "aws": "AccessDeniedException"}[cloud]
                    check(tag + " -> 403 native", r.status_code == 403 and code in r.text and bool(r.headers.get("x-cloudlearn-tier-denied")), (r.status_code, r.text[:150]))
    set_lic("free")
except TypeError as e:   # server.py cannot be imported on Python 3.9 (pydantic `X | None` annotations)
    print(f"[SKIP] HTTP middleware section: server.py not importable on this Python ({sys.version.split()[0]}): {str(e)[:80]}")
except Exception as e:  # pragma: no cover
    import traceback
    traceback.print_exc()
    check("HTTP middleware section ran", False, repr(e))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
