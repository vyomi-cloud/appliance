#!/usr/bin/env python3
"""Build Vyomi Nano's in-browser Kubescape evaluator (OPA -> WebAssembly).

Kubescape (https://github.com/kubescape/kubescape) is Go and cannot run under
Pyodide. Its controls, however, are plain Rego (kubescape/regolibrary, Apache-2.0),
so the SAME rule source can be compiled to WebAssembly with OPA (`opa build -t wasm`)
and evaluated in the page / shared worker with @open-policy-agent/opa-wasm. This
script takes the regolibrary artifacts Kubescape itself downloads
(`kubescape download artifacts --output <dir>`) and writes:

  policy.wasm    one wasm module, one entrypoint per included rule
                 (armo_builtins/r<N>/deny — the rule's package, renamed so rules don't collide)
  controls.json  the included controls (+ rule match/config inputs, the controls-inputs
                 the CLI feeds them, and Kubescape's default system exceptions)
  catalog.json   metadata for EVERY control of the scanned frameworks (also used by the
                 offline appliance to map real Kubescape CLI results)

Only controls whose rules ks-eval.mjs can evaluate EXACTLY like Kubescape's
opaprocessor are included: file-scannable controls whose rules have no
ResourceEnumerator, no RegoResourcesAggregator, no rule dependencies and no
Kubescape-custom builtins. Parity is proven against the real CLI by
tests/conformance/test_kubescape_wasm_parity.mjs.

Usage:
    python3 wasm/kubescape/build_kubescape_wasm.py <artifacts-dir> [--opa /path/to/opa]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMEWORKS = ["nsa", "mitre", "cis-v1.12.0"]          # what the offline scan runs (framework file names)
KUBESCAPE_VERSION = "v4.0.16"
OPA_VERSION = "1.21.1"
CUSTOM_BUILTINS = re.compile(r"\b(image\.parse_normalized_name|cosign\.[a-z_]+)\s*\(")
# Controls that pass every structural filter but were measured NOT to reach exact parity
# with the CLI (see the parity test) — none so far.
PARITY_EXCLUDED: dict = {}


def severity(base_score) -> str:
    """Kubescape's apis.ControlSeverityToString over the control's baseScore."""
    try:
        s = float(base_score)
    except (TypeError, ValueError):
        return "Unknown"
    if s < 1:
        return "Unknown"
    if s < 4:
        return "Low"
    if s < 7:
        return "Medium"
    if s < 9:
        return "High"
    return "Critical"


def exclusion_reasons(control: dict) -> list:
    reasons = []
    if "file" not in ((control.get("scanningScope") or {}).get("matches") or []):
        reasons.append("not file-scannable (needs live cluster / cloud / host data)")
    rules = control.get("rules") or []
    if not rules:
        reasons.append("no Rego rules (manual control)")
    for r in rules:
        if (r.get("ruleLanguage") or "Rego").lower() != "rego":
            reasons.append(f"{r['name']}: non-Rego rule")
        if r.get("resourceEnumerator"):
            reasons.append(f"{r['name']}: uses a ResourceEnumerator pre-pass")
        if (r.get("attributes") or {}).get("resourcesAggregator"):
            reasons.append(f"{r['name']}: uses the {r['attributes']['resourcesAggregator']} resource aggregator")
        if r.get("ruleDependencies"):
            reasons.append(f"{r['name']}: depends on Kubescape Rego libraries")
        if r.get("dynamicMatch"):
            reasons.append(f"{r['name']}: dynamic (host-sensor / cloud) match")
        if CUSTOM_BUILTINS.search(r.get("rule") or ""):
            reasons.append(f"{r['name']}: uses Kubescape-custom builtins")
    if control["controlID"] in PARITY_EXCLUDED:
        reasons.append(PARITY_EXCLUDED[control["controlID"]])
    return reasons


def _package_value_rules(opa: str, path: str) -> set:
    """Names of the non-function rules a module defines (what data.<package> evaluates to)."""
    p = subprocess.run([opa, "parse", "--format", "json", path], capture_output=True, text=True, check=True)
    names = set()
    for r in json.loads(p.stdout).get("rules", []):
        h = r["head"]
        if h.get("args"):
            continue
        names.add(h.get("name") or str((h.get("ref") or [{}])[0].get("value")))
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifacts")
    ap.add_argument("--opa", default=shutil.which("opa") or "opa")
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args()

    controls: dict = {}
    frameworks_of: dict = {}
    fw_names = []
    for fw in FRAMEWORKS:
        doc = json.load(open(os.path.join(a.artifacts, fw + ".json")))
        fw_names.append(doc["name"])
        for c in doc["controls"]:
            controls.setdefault(c["controlID"], c)
            frameworks_of.setdefault(c["controlID"], []).append(doc["name"])
    inputs = json.load(open(os.path.join(a.artifacts, "controls-inputs.json")))
    exceptions = json.load(open(os.path.join(a.artifacts, "exceptions.json")))

    catalog = {}
    included, excluded = [], {}
    for cid in sorted(controls):
        c = controls[cid]
        catalog[cid] = {
            "controlID": cid, "name": c.get("name"), "severity": severity(c.get("baseScore")),
            "baseScore": c.get("baseScore"), "description": c.get("description") or "",
            "remediation": c.get("remediation") or "", "category": (c.get("category") or {}).get("name") or "",
            "subCategory": ((c.get("category") or {}).get("subCategory") or {}).get("name") or "",
            "frameworks": frameworks_of[cid],
            "nanoEvaluable": False,
        }
        why = exclusion_reasons(c)
        if why:
            excluded[cid] = why
        else:
            included.append(cid)
            catalog[cid]["nanoEvaluable"] = True

    # unique rules (by name) across the included controls -> one renamed package each
    rule_ids: dict = {}
    rule_defs = []
    tmp = tempfile.mkdtemp(prefix="vyomi-ks-build-")
    try:
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        for cid in included:
            for r in controls[cid]["rules"]:
                if r["name"] in rule_ids:
                    continue
                n = len(rule_defs)
                rule_ids[r["name"]] = n
                src, k = re.subn(r"(?m)^package\s+armo_builtins\s*$", f"package armo_builtins.r{n}", r["rule"])
                if k != 1:
                    raise SystemExit(f"rule {r['name']}: expected exactly one 'package armo_builtins' line")
                with open(os.path.join(src_dir, f"r{n}.rego"), "w") as f:
                    f.write(src)
                # Kubescape queries the whole package (data.armo_builtins) and parses EVERY
                # value in it as []RuleResponse; a package with any non-function rule besides
                # `deny` would differ from evaluating `deny` alone, so refuse it here.
                heads = _package_value_rules(a.opa, os.path.join(src_dir, f"r{n}.rego"))
                if heads != {"deny"}:
                    raise SystemExit(f"rule {r['name']}: package values {sorted(heads)} != {{'deny'}} — add its control to PARITY_EXCLUDED")
                rule_defs.append({
                    "name": r["name"], "entrypoint": f"armo_builtins/r{n}/deny",
                    "match": r.get("match") or [],
                    "configInputs": [i.get("path") for i in (r.get("controlConfigInputs") or []) if i.get("path")],
                })
        # Kubescape compiles every rule together with its always-loaded helper library
        # (opa-utils resources.LoadRegoModules -> package cautils), so the bundle carries it too.
        shutil.copy(os.path.join(HERE, "cautils.rego"), os.path.join(src_dir, "cautils.rego"))
        bundle = os.path.join(tmp, "bundle.tar.gz")
        cmd = [a.opa, "build", "-t", "wasm", "-o", bundle]   # Rego v1 first, like getCompiledRule
        for d in rule_defs:
            cmd += ["-e", d["entrypoint"]]
        cmd.append(src_dir)
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            sys.stderr.write(p.stdout + p.stderr)
            return 1
        with tarfile.open(bundle) as t:
            wasm = t.extractfile("/policy.wasm").read()
            manifest = json.load(t.extractfile("/.manifest"))
        # entrypoint ids as compiled (opa-wasm resolves entrypoints by name too)
        with open(os.path.join(a.out, "policy.wasm"), "wb") as f:
            f.write(wasm)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # The artifacts carry no regolibrary release tag, so pin them by content hash.
    h = hashlib.sha256()
    for fn in [f + ".json" for f in FRAMEWORKS] + ["controls-inputs.json", "exceptions.json"]:
        h.update(open(os.path.join(a.artifacts, fn), "rb").read())
    version = {"kubescape": KUBESCAPE_VERSION, "opa": OPA_VERSION, "frameworks": fw_names,
               "regolibrary": "artifacts downloaded by kubescape " + KUBESCAPE_VERSION + " (`kubescape download artifacts`)",
               "artifactsSha256": h.hexdigest()}
    out_controls = {
        "version": version,
        "controls": [{
            "controlID": cid, "name": controls[cid].get("name"), "severity": catalog[cid]["severity"],
            "baseScore": controls[cid].get("baseScore"), "description": catalog[cid]["description"],
            "remediation": catalog[cid]["remediation"], "category": catalog[cid]["category"],
            "frameworks": frameworks_of[cid],
            "actionRequired": (controls[cid].get("attributes") or {}).get("actionRequired") or "",
            "rules": [rule_ids[r["name"]] for r in controls[cid]["rules"]],
        } for cid in included],
        "rules": rule_defs,
        "controlsInputs": inputs,
        "exceptions": [e for e in exceptions if e.get("policyType") == "postureExceptionPolicy"],
        "excluded": excluded,
    }
    with open(os.path.join(a.out, "controls.json"), "w") as f:
        json.dump(out_controls, f, indent=1, sort_keys=False)
    with open(os.path.join(a.out, "catalog.json"), "w") as f:
        json.dump({"version": version, "controls": catalog}, f, indent=1)
    print(f"{len(included)} controls / {len(rule_defs)} rules compiled -> policy.wasm ({len(wasm)} bytes); "
          f"{len(excluded)} controls excluded; catalog {len(catalog)} controls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
