"""Kubescape posture results for an AKS cluster (substrate-free) — the Kubernetes backend of
Microsoft Defender for Cloud in Vyomi.

Kubescape (https://github.com/kubescape/kubescape) scans Kubernetes objects against the NSA-CISA,
MITRE ATT&CK and CIS Kubernetes frameworks (Rego controls from kubescape/regolibrary). Vyomi feeds
it the objects a cluster really holds (core/azure_aks_k8s_core.py — what `kubectl apply` stored
through runCommand) and keeps the parsed result ON the cluster's ARM record
(``rec["_kubescape"]``), where the Microsoft.Security engine (core/azure_security_core.py) reads
it to build Defender assessments.

Who runs the scan is substrate-specific and plugged in through ``set_scanner``:

  * offline appliance — providers/kubescape_runner.py runs the real Kubescape CLI container
    (pinned image below, air-gapped artifacts, no telemetry) in a background thread, debounced
    after object changes; if Docker or the image is unavailable the result says so;
  * Nano — the browser has no Docker, so ``WasmScanner`` calls the in-page evaluator
    (wasm/kubescape/ks-eval.mjs: the SAME regolibrary Rego compiled to WebAssembly with OPA) via
    ``globalThis.__vyomi_kubescape_eval``; it covers the subset of controls that evaluator
    includes and the result records exactly which.

Never fabricated: with no scanner the status is ``unavailable`` with the reason, and the
Defender engine shows no Kubernetes findings for that cluster.
"""
from __future__ import annotations

import datetime
import json
import re

try:
    from core import kubescape_catalog as _cat
    from core import azure_aks_k8s_core as k8s
except ImportError:                                    # Pyodide flat layout
    import kubescape_catalog as _cat                   # type: ignore
    import azure_aks_k8s_core as k8s                   # type: ignore

KUBESCAPE_VERSION = "v4.0.16"
IMAGE = "quay.io/kubescape/kubescape-cli:v4.0.16@sha256:d575d4f2281473ce539d41053d63482a4e9e07f35d987206b2bac79b2c9ad4bc"
FRAMEWORKS = list(_cat.FRAMEWORKS)                    # nsa, mitre, cis-v1.12.0
CATALOG = _cat.CONTROLS


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── report parsing (CLI JSON report, or the same shape from the wasm evaluator) ──────────
_API = re.compile(r"api=([^/]*)/([^/]+)/([^/]*)/([^/]+)/([^/]+)")
_LEAD = re.compile(r"^/([^/]*)/([^/]+)/([^/]+)")
_TAIL = re.compile(r"/([^/]*)//(User|Group)/([^/]+)$")


def parse_resource_id(rid: str) -> list:
    """Kubescape resourceID -> [{apiVersion, namespace, kind, name}] components, subject first.

    File-scan ids look like ``path=123/api=apps/v1/shop/Deployment/web``; RBAC findings are
    "vectors" chaining subject + binding + role (``/shop/ServiceAccount/sa/path=…/api=…/
    ClusterRoleBinding/b/path=…/api=…/ClusterRole/r``, or ending in ``group//User/jane``)."""
    comps = []
    m = _LEAD.match(rid)
    if m and not rid.startswith("/path=") and m.group(2)[:1].isupper():
        comps.append({"apiVersion": "v1", "namespace": m.group(1), "kind": m.group(2), "name": m.group(3), "subject": True})
    for g, v, ns, kind, name in _API.findall(rid):
        comps.append({"apiVersion": f"{g}/{v}" if g else v, "namespace": ns, "kind": kind, "name": name})
    t = _TAIL.search(rid)
    if t:
        comps.append({"apiVersion": f"{t.group(1)}/v1" if t.group(1) else "v1", "namespace": "", "kind": t.group(2),
                      "name": t.group(3), "subject": True})
    if not comps:                                      # cluster-scan form: group/version/ns/Kind/name
        parts = rid.strip("/").split("/")
        if len(parts) >= 4:
            kind, name, ns = parts[-2], parts[-1], parts[-3]
            av = "/".join(parts[:-3]) or "v1"
            comps.append({"apiVersion": av, "namespace": ns, "kind": kind, "name": name})
    subj = [c for c in comps if c.get("subject")]
    rest = [c for c in comps if not c.get("subject")]
    for c in comps:
        c.pop("subject", None)
    return subj + rest


def parse_report(report: dict, engine: str) -> dict:
    """Kubescape JSON report -> {controls: [finding…], frameworks: {name: score}, …}."""
    summary = (report or {}).get("summaryDetails") or {}
    controls = {}
    for cid, c in (summary.get("controls") or {}).items():
        meta = CATALOG.get(cid, {})
        si = c.get("statusInfo") or {}
        rc = c.get("ResourceCounters") or {}
        controls[cid] = {
            "controlId": cid,
            "name": c.get("name") or meta.get("name") or cid,
            "severity": c.get("severity") or meta.get("severity") or "Unknown",
            "status": c.get("status") or si.get("status") or "passed",
            "subStatus": si.get("subStatus") or "",
            "failedCount": int(rc.get("failedResources") or 0),
            "passedCount": int(rc.get("passedResources") or 0),
            "skippedCount": int(rc.get("skippedResources") or 0),
            "category": ((c.get("category") or {}).get("name")) or meta.get("category", ""),
            "description": meta.get("description", ""),
            "remediation": meta.get("remediation", ""),
            "frameworks": meta.get("frameworks", []),
            "complianceScore": c.get("complianceScore"),
            "failed": [],
        }
    for r in (report or {}).get("results") or []:
        comps = parse_resource_id(str(r.get("resourceID") or ""))
        if not comps:
            continue
        primary, related = comps[0], comps[1:]
        for ctl in r.get("controls") or []:
            st = (ctl.get("status") or {}).get("status") if isinstance(ctl.get("status"), dict) else ctl.get("status")
            if st != "failed":
                continue
            cid = ctl.get("controlID")
            f = controls.get(cid)
            if f is None:
                continue
            fix, failed_paths, review = [], [], []
            for rule in ctl.get("rules") or []:
                for p in rule.get("paths") or []:
                    if p.get("fixPath"):
                        fix.append({"path": p["fixPath"].get("path"), "value": p["fixPath"].get("value")})
                    if p.get("failedPath"):
                        failed_paths.append(p["failedPath"])
                    if p.get("reviewPath"):
                        review.append(p["reviewPath"])
                    if p.get("deletePath"):
                        failed_paths.append(p["deletePath"])
            entry = dict(primary)
            entry["related"] = related
            entry["fixPaths"] = fix
            entry["failedPaths"] = failed_paths
            entry["reviewPaths"] = review
            key = (entry["kind"], entry["namespace"], entry["name"])
            if any((e["kind"], e["namespace"], e["name"]) == key for e in f["failed"]):
                continue
            f["failed"].append(entry)
    frameworks = {fw.get("name"): fw.get("complianceScore") for fw in (summary.get("frameworks") or [])}
    return {"engine": engine, "controls": sorted(controls.values(), key=lambda x: x["controlId"]),
            "frameworks": frameworks, "complianceScore": summary.get("complianceScore"),
            "controlsEvaluated": sorted(controls)}


# ── result storage on the cluster record ────────────────────────────────────────────────
def result(rec: dict) -> dict | None:
    return rec.get("_kubescape")


def store_result(rec: dict, status: str, *, engine: str = "", reason: str = "", parsed: dict | None = None,
                 objects_version: int | None = None, frameworks=None) -> dict:
    prev = rec.get("_kubescape") or {}
    out = {"status": status, "engine": engine or prev.get("engine", ""), "reason": reason,
           "kubescapeVersion": KUBESCAPE_VERSION, "frameworks": list(frameworks or FRAMEWORKS),
           "objectsVersion": objects_version if objects_version is not None else k8s.version(rec),
           "updatedAt": _now()}
    if parsed is not None:
        out.update({"scannedAt": _now(), "controls": parsed["controls"], "frameworkScores": parsed.get("frameworks", {}),
                    "complianceScore": parsed.get("complianceScore"), "controlsEvaluated": parsed.get("controlsEvaluated", [])})
    elif status in ("running", "queued") and prev.get("controls") is not None:
        # keep the last completed scan visible while the next one runs (marked stale by objectsVersion)
        for k in ("scannedAt", "controls", "frameworkScores", "complianceScore", "controlsEvaluated"):
            if k in prev:
                out[k] = prev[k]
        out["lastObjectsVersion"] = prev.get("lastObjectsVersion", prev.get("objectsVersion"))
    if parsed is not None:
        out["lastObjectsVersion"] = out["objectsVersion"]
    rec["_kubescape"] = json.loads(json.dumps(out))   # JSON-safe by construction
    return rec["_kubescape"]


def is_fresh(rec: dict) -> bool:
    r = rec.get("_kubescape") or {}
    return r.get("status") == "succeeded" and r.get("lastObjectsVersion") == k8s.version(rec)


# ── scanners ────────────────────────────────────────────────────────────────────────────
class WasmScanner:
    """Nano: the in-browser OPA-wasm evaluator of the regolibrary controls (synchronous)."""
    engine = "opa-wasm"

    def request(self, rec: dict, rid: str, reason: str = "") -> None:
        try:
            import js                                  # type: ignore  # Pyodide only
        except ImportError:
            store_result(rec, "unavailable", engine=self.engine,
                         reason="Kubernetes posture scanning runs on the offline appliance (Kubescape CLI); "
                                "this runtime has no Kubescape evaluator")
            return
        fn = getattr(js.globalThis, "__vyomi_kubescape_eval", None)
        if fn is None:
            store_result(rec, "unavailable", engine=self.engine,
                         reason="The in-browser Kubescape evaluator (OPA WebAssembly) is not loaded in this context")
            return
        v = k8s.version(rec)
        try:
            raw = fn(json.dumps(k8s.export_objects(rec)))
            report = json.loads(str(raw))
        except Exception as e:                         # surface, never fake
            store_result(rec, "failed", engine=self.engine, reason=f"In-browser Kubescape evaluation failed: {e}")
            return
        parsed = parse_report(report, self.engine)
        store_result(rec, "succeeded", engine=self.engine, parsed=parsed, objects_version=v)


class _NoScanner:
    engine = ""

    def request(self, rec: dict, rid: str, reason: str = "") -> None:
        store_result(rec, "unavailable", reason="No Kubernetes posture scanner is configured in this runtime")


_SCANNER = WasmScanner()


def set_scanner(scanner) -> None:
    global _SCANNER
    _SCANNER = scanner


def scanner():
    return _SCANNER


def on_objects_changed(rec: dict, rid: str) -> None:
    """The cluster's object store moved — (re)scan (Nano: now; offline: debounced, background)."""
    try:
        _SCANNER.request(rec, rid, "objects-changed")
    except Exception as e:                             # a scanner fault never fails the kubectl call
        store_result(rec, "failed", reason=f"Scanner error: {e}")


def ensure_fresh(rec: dict, rid: str) -> None:
    """Called on Defender reads (Defender assesses continuously): rescan a stale or never-scanned
    cluster — non-blocking offline. An unavailable/failed scanner is retried at most once a
    minute for the same object set, so reads never hammer a missing Docker daemon."""
    r = rec.get("_kubescape") or {}
    if is_fresh(rec) or r.get("status") in ("running", "queued"):
        return
    if r.get("status") in ("unavailable", "failed") and r.get("objectsVersion") == k8s.version(rec):
        try:
            age = (datetime.datetime.now(datetime.timezone.utc)
                   - datetime.datetime.strptime(r.get("updatedAt", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)).total_seconds()
        except ValueError:
            age = 1e9
        if age < 60:
            return
    on_objects_changed(rec, rid)
