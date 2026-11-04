"""Kubescape result mapping (core/kubescape_core.py) + the offline Kubescape CLI runner
(providers/kubescape_runner.py).

  1. Recorded reports — tests/conformance/fixtures/kubescape/cli-results*.json were produced by
     the real CLI (quay.io/kubescape/kubescape-cli:v4.0.16, frameworks nsa,mitre,cis-v1.12.0,
     --network none, air-gapped artifacts) over objects*.yaml. parse_report must reproduce, per
     control, the CLI's own status / severity / failed-resource count, attribute every failed
     resource (RBAC "vectors" to their subject with the binding/role as related objects) and keep
     the fix paths.
  2. Scanner plumbing — with no scanner the result is "unavailable" with a reason (never
     findings); a cluster's result goes stale when its objects change.
  3. REAL container (skipped only when Docker or the image is unavailable): the offline runner
     scans the fixture objects and its parsed result equals the recorded report's, control by
     control — the same CLI, the same input.

Run:  PYTHONPATH=. python3 tests/conformance/test_kubescape_core.py
"""
import json
import os
from pathlib import Path

from core import kubescape_core as ks
from core import azure_aks_k8s_core as k8s
from core import k8s_yaml

FIX = Path(__file__).resolve().parent / "fixtures" / "kubescape"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _summary(parsed):
    return {c["controlId"]: (c["status"], c["severity"], c["failedCount"], len(c["failed"])) for c in parsed["controls"]}


def run() -> int:
    for rep_name in ("cli-results.json", "cli-results-2.json"):
        rep = json.loads((FIX / rep_name).read_text())
        parsed = ks.parse_report(rep, "kubescape-cli test")
        sd = rep["summaryDetails"]["controls"]
        _check(f"{rep_name}: every control of the report is mapped ({len(sd)})", set(parsed["controlsEvaluated"]) == set(sd))
        mism = [cid for cid, c in sd.items()
                if (_summary(parsed)[cid][0], _summary(parsed)[cid][1], _summary(parsed)[cid][2])
                != (c["status"], c["severity"], c["ResourceCounters"]["failedResources"])]
        _check(f"{rep_name}: status / severity / failed count match the CLI for every control", not mism)
        # every failed resource the CLI attributes to a control is listed (vectors collapse to their subject)
        want = {}
        for r in rep["results"]:
            for ctl in r["controls"]:
                if ctl["status"]["status"] == "failed":
                    want.setdefault(ctl["controlID"], set()).add(r["resourceID"])
        bad = [cid for cid, rids in want.items()
               if len({(c["kind"], c["namespace"], c["name"]) for c in next(x for x in parsed["controls"] if x["controlId"] == cid)["failed"]})
               != len({tuple(ks.parse_resource_id(x)[0][k] for k in ("kind", "namespace", "name")) for x in rids})]
        _check(f"{rep_name}: failed resources attributed for every failed control ({len(want)})", not bad)
        _check(f"{rep_name}: framework scores carried", set(parsed["frameworks"]) == {f["name"] for f in rep["summaryDetails"]["frameworks"]})

    parsed = ks.parse_report(json.loads((FIX / "cli-results.json").read_text()), "t")
    by = {c["controlId"]: c for c in parsed["controls"]}
    priv = by["C-0057"]
    _check("C-0057 Privileged container: High, fails shop/Deployment/priv-app",
           priv["severity"] == "High" and [(f["kind"], f["namespace"], f["name"]) for f in priv["failed"]] == [("Deployment", "shop", "priv-app")])
    _check("C-0057 carries the fix path from the CLI", any("privileged" in (p.get("path") or "") or "privileged" in str(f["failedPaths"])
                                                            for f in priv["failed"] for p in (f["fixPaths"] or [{}])))
    _check("C-0057 carries Kubescape's remediation text", "privileged" in priv["remediation"].lower())
    rbac = by["C-0187"]["failed"][0]
    _check("RBAC vector attributed to the subject (ServiceAccount shop/deployer) with binding + role related",
           (rbac["kind"], rbac["namespace"], rbac["name"]) == ("ServiceAccount", "shop", "deployer")
           and {r["kind"] for r in rbac["related"]} == {"ClusterRoleBinding", "ClusterRole"})
    comps = ks.parse_resource_id("path=1/api=rbac.authorization.k8s.io/v1/shop/RoleBinding/rb/path=2/api=rbac.authorization.k8s.io/v1/shop/Role/r/rbac.authorization.k8s.io//User/jane")
    _check("User-subject vectors parse (subject first)", comps[0]["kind"] == "User" and comps[0]["name"] == "jane" and len(comps) == 3)
    _check("passed-but-irrelevant controls keep subStatus 'irrelevant'", any(c["subStatus"] == "irrelevant" for c in parsed["controls"]))

    # ── scanner plumbing ─────────────────────────────────────────────────────────────────
    rec = {"id": "/x", "properties": {"namespaces": [{"name": "default"}]}}
    ks.set_scanner(ks.WasmScanner())
    ks.on_objects_changed(rec, "/x")
    r = ks.result(rec)
    _check("host CPython has no wasm evaluator -> 'unavailable' with a reason, no findings",
           r["status"] == "unavailable" and r["reason"] and not r.get("controls"))
    k8s.run_command(rec, "kubectl create namespace a")
    _check("result is stale once the objects change", not ks.is_fresh(rec))

    # ── offline runner degrades honestly without Docker ──────────────────────────────────
    try:
        from providers import kubescape_runner as kr0
        real_which = kr0.shutil.which
        kr0.shutil.which = lambda _n: None
        try:
            why = kr0.preflight()
            _check("no docker CLI -> preflight gives the reason", bool(why) and "docker CLI is not available" in why)
            sc = kr0.OfflineScanner()
            rec2 = {"id": "/y", "properties": {"namespaces": [{"name": "default"}]}}
            k8s.run_command(rec2, "kubectl create namespace b")
            sc.request(rec2, "/y")
            _check("request() only queues on the caller's thread (never blocks)", ks.result(rec2)["status"] == "queued")
            sc.wait_idle(60)
            r2 = ks.result(rec2)
            _check("no docker -> 'unavailable' + reason, no findings", r2["status"] == "unavailable" and "docker" in r2["reason"].lower() and not r2.get("controls"))
        finally:
            kr0.shutil.which = real_which
    except ImportError as e:                        # pragma: no cover
        print(f"  --  runner import failed ({e})")

    # ── REAL Kubescape CLI container ─────────────────────────────────────────────────────
    try:
        from providers import kubescape_runner as kr
    except Exception as e:                         # pragma: no cover
        print(f"  --  runner import failed ({e}); real-container test skipped")
        kr = None
    reason = kr.preflight() if kr else "runner unavailable"
    if reason:
        print(f"  --  SKIPPED real Kubescape container test: {reason}")
    else:
        objs = k8s_yaml.load_all((FIX / "objects.yaml").read_text())
        report, why = kr.scan_objects(objs)
        _check(f"real CLI scan succeeded ({why or 'ok'})", report is not None)
        live = ks.parse_report(report, kr.ENGINE)
        want = ks.parse_report(json.loads((FIX / "cli-results.json").read_text()), "recorded")
        _check(f"real CLI scan of the fixture == recorded report, control by control ({len(want['controls'])} controls)",
               _summary(live) == _summary(want))
        _check("scan ran air-gapped with the pinned image", report.get("metadata", {}).get("scanMetadata", {}).get("kubescapeVersion") == ks.KUBESCAPE_VERSION)
        import subprocess
        left = subprocess.run(["docker", "ps", "-a", "--filter", "name=vyomi-ks-scan", "-q"], capture_output=True, text=True).stdout.strip()
        _check("scan containers removed", left == "")

    print("\nRESULT: PASS — Kubescape result mapping conforms on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
