# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Managed-Kubernetes tier gate (AKS / GKE / EKS) -- shared by the appliance server and Nano (Pyodide).

Policy (single source of truth is core/tier_policy.py: category ``kubernetes``):
    managed Kubernetes is Pro / Max / Enterprise ONLY.  Free and the legacy API-only tiers
    (nano, micro, lite) are completely restricted -- control plane, runCommand/kubectl data plane,
    Backup-for-AKS / Backup-for-GKE, Flux/GitOps.  Pro keeps its primary-cloud rule (only the
    primary cloud's Kubernetes); Max / Enterprise get all three clouds.

This module is pure stdlib (+ an optional tier_policy import) so the SAME file is vendored into the
Nano bundle (wasm/core/).  It has three jobs:

  * ``classify(path, headers)`` -> "azure" | "gcp" | "aws" | None: is this request a managed-Kubernetes
    request (any plane)?  One regex table, used by the HTTP middleware, the wire router and the cores.
  * ``check(cloud)`` -> None (allowed / not enforced) | dict (denied): resolves the ACTIVE tier from a
    registered provider and applies the policy.
  * ``denied_response(cloud, verdict)`` -> {status, headers, body(bytes)}: a native-style error
    (ARM ``FeatureNotAvailableForTier``, EKS ``AccessDeniedException``, GCP ``PERMISSION_DENIED``).

Where the tier comes from:
  * appliance server: ``set_provider(fn)`` (server.py) -> (tier, primary_cloud) of the active tenant, or
    None when tier enforcement is switched off (CLOUDLEARN_TIER_ENFORCE=0).
  * Nano: ``arm_nano()`` is called at boot and FAILS CLOSED (tier "free") until ``set_tier(tier, primary)``
    delivers the licence tier read from the service worker (/api/runtime/tier).
  * bare cores (unit tests, hosts that register nothing): not enforced.
"""
from __future__ import annotations

import json
import re

CATEGORY = "kubernetes"
KUBERNETES_TIERS = ("pro", "max", "enterprise")
SERVICE_KEY = {"azure": "aks", "gcp": "gke", "aws": "eks"}
_CLOUD_NAME = {"azure": "AKS (Azure Kubernetes Service)", "gcp": "GKE (Google Kubernetes Engine)",
               "aws": "EKS (Elastic Kubernetes Service)"}

# ---------------------------------------------------------------------------
# Request classification
# ---------------------------------------------------------------------------
# Azure: the AKS control plane, runCommand / kubectl (a POST under managedClusters), Flux / GitOps
# (Microsoft.KubernetesConfiguration) and Azure Backup for AKS (Microsoft.DataProtection -- the engine
# serves AKS datasources only).
_AZ = re.compile(r"/providers/microsoft\.(containerservice|kubernetesconfiguration|dataprotection)(/|$)", re.I)
# GCP: clusters (+ the /k8s/ kubectl data plane beneath them), serverConfig, Backup for GKE, and the
# classic console REST (/api/container/*, /api/sub/container/*).  ``operations`` is deliberately NOT
# gated: that collection is shared with Memorystore and reveals nothing about a cluster.
_GCP = re.compile(r"^/v1(beta1)?/projects/[^/]+/(locations|zones)/[^/]+/(clusters|serverConfig|backupPlans)([/:]|$)")
_GCP_CONSOLE = ("/api/container/", "/api/sub/container/")
_GCP_CONSOLE_EXACT = ("/api/container",)
# AWS EKS is a REST API (eks.<region>.amazonaws.com/clusters...); identified by its SigV4 credential scope.
_AWS_SCOPE = re.compile(r"Credential=[^/\s]+/\d+/[^/]+/eks/aws4_request", re.I)


def classify(path, headers=None):
    p = str(path or "").split("?", 1)[0]
    i = p.find("/_wire/")            # the v4 consoles' same-origin wire prefix (appliance /_wire, Nano /nano/_wire)
    if i >= 0:
        p = p[i + len("/_wire"):]
    if _AZ.search(p):
        return "azure"
    if _GCP.search(p) or p.startswith(_GCP_CONSOLE) or p in _GCP_CONSOLE_EXACT:
        return "gcp"
    if p.startswith("/eks/") or p.startswith("/api/eks/"):
        return "aws"
    if headers:
        lh = {str(k).lower(): str(v) for k, v in dict(headers).items()}
        auth = lh.get("authorization", "")
        if _AWS_SCOPE.search(auth):
            return "aws"
    return None


# ---------------------------------------------------------------------------
# Active tier
# ---------------------------------------------------------------------------
_PROVIDER = None            # callable -> (tier, primary_cloud) | None (= not enforced)
_NANO = {"armed": False, "tier": "free", "primary": ""}


def set_provider(fn):
    """Register the appliance's tier source (server.py). ``fn()`` -> (tier, primary) or None."""
    global _PROVIDER
    _PROVIDER = fn


def arm_nano():
    """Nano boot: enforce from now on, failing CLOSED (free) until set_tier() is called."""
    _NANO["armed"] = True


def set_tier(tier, primary_cloud=""):
    _NANO.update(armed=True, tier=str(tier or "free"), primary=str(primary_cloud or ""))


def _norm(tier):
    try:
        from core import tier_policy as _tp
        return _tp.normalize_tier(tier)
    except Exception:
        t = str(tier or "free").strip().lower()
        t = {"student": "pro", "edu": "pro", "developer": "max", "dev": "max"}.get(t, t)
        return t if t in ("free", "nano", "micro", "lite", "pro", "max", "enterprise") else "free"


def _active():
    if _PROVIDER is not None:
        try:
            return _PROVIDER()
        except Exception:
            return ("free", "")          # a broken provider must never open the gate
    if _NANO["armed"]:
        return (_NANO["tier"], _NANO["primary"])
    return None


def verdict(tier, cloud, primary_cloud=""):
    """Pure policy decision: None if allowed, else a dict describing the denial."""
    t = _norm(tier)
    svc = SERVICE_KEY.get(cloud, "kubernetes")
    if t not in KUBERNETES_TIERS:
        return {"ok": False, "code": "tier_service_locked", "category": CATEGORY, "service": svc,
                "provider": cloud, "active_tier": t, "required_tiers": ["pro", "max", "enterprise"],
                "upgrade_to": "pro",
                "reason": f"Managed Kubernetes ({_CLOUD_NAME.get(cloud, svc)}) requires the Pro, Max or Enterprise tier; "
                          f"the active tier is {t.capitalize()}."}
    if t == "pro":
        if not primary_cloud:
            return {"ok": False, "code": "tier_primary_cloud_unset", "category": CATEGORY, "service": svc,
                    "provider": cloud, "active_tier": t, "required_tiers": ["max", "enterprise"], "upgrade_to": "max",
                    "reason": "Pro tier requires a primary cloud to be selected before managed Kubernetes can be used."}
        if primary_cloud != cloud:
            return {"ok": False, "code": "tier_provider_locked", "category": CATEGORY, "service": svc,
                    "provider": cloud, "active_tier": t, "required_tiers": ["max", "enterprise"], "upgrade_to": "max",
                    "reason": f"Pro tier is locked to {primary_cloud}; managed Kubernetes on {cloud} requires the Max or Enterprise tier."}
    return None


def check(cloud):
    st = _active()
    if st is None:
        return None
    tier, primary = st
    return verdict(tier, cloud, primary)


def is_locked(cloud):
    return check(cloud) is not None


# ---------------------------------------------------------------------------
# Native-style denial
# ---------------------------------------------------------------------------
def denied_response(cloud, v):
    msg = v["reason"]
    extra = {"activeTier": v["active_tier"], "requiredTiers": v["required_tiers"], "upgradeTo": v["upgrade_to"]}
    if cloud == "azure":
        body = {"error": {"code": "FeatureNotAvailableForTier", "message": msg, "details": [extra]}}
        headers = {"content-type": "application/json", "x-ms-error-code": "FeatureNotAvailableForTier"}
    elif cloud == "gcp":
        body = {"error": {"code": 403, "message": msg, "status": "PERMISSION_DENIED",
                          "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "TIER_REQUIRED",
                                       "domain": "vyomi.cloud",
                                       "metadata": {"activeTier": v["active_tier"], "requiredTiers": ",".join(v["required_tiers"]),
                                                    "upgradeTo": v["upgrade_to"]}}]}}
        headers = {"content-type": "application/json"}
    else:
        body = {"__type": "AccessDeniedException", "message": msg, **extra}
        headers = {"content-type": "application/json", "x-amzn-ErrorType": "AccessDeniedException"}
    headers["X-CloudLearn-Tier-Denied"] = v["code"]
    return {"status": 403, "headers": headers, "body": json.dumps(body).encode()}


def gate(path, headers=None, cloud=None):
    """One call for request-shaped entry points: None to proceed, else a denied_response dict."""
    c = cloud or classify(path, headers)
    if not c:
        return None
    v = check(c)
    return denied_response(c, v) if v else None


def ui_verdicts():
    """{cloud: {locked, reason, required_tiers}} for the consoles (GET /api/runtime/tier -> kubernetes_locked).
    The consoles show exactly what the server will enforce; when enforcement is off nothing is locked."""
    out = {}
    for c in ("azure", "gcp", "aws"):
        v = check(c)
        out[c] = {"locked": bool(v), "reason": (v or {}).get("reason", ""), "required_tiers": (v or {}).get("required_tiers", [])}
    return out
