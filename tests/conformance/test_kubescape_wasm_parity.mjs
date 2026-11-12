// Parity: Vyomi Nano's OPA-wasm Kubescape evaluator (wasm/kubescape/ks-eval.mjs) vs the REAL
// Kubescape CLI (quay.io/kubescape/kubescape-cli:v4.0.16, frameworks nsa,mitre,cis-v1.12.0,
// file scan of the same objects, offline artifacts). The CLI reports are recorded fixtures in
// tests/conformance/fixtures/kubescape/. For EVERY control the evaluator includes, the failed
// resource set and the per-control failed/passed/excluded counts must be identical.
//
//   node tests/conformance/test_kubescape_wasm_parity.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const FIX = path.join(ROOT, "tests/conformance/fixtures/kubescape");
const { installKubescape } = await import(path.join(ROOT, "wasm/kubescape/ks-eval.mjs"));

const controls = JSON.parse(readFileSync(path.join(ROOT, "wasm/kubescape/controls.json"), "utf8"));
const wasm = readFileSync(path.join(ROOT, "wasm/kubescape/policy.wasm"));
const info = await installKubescape(null, { controls, wasm });

const CASES = [
  ["objects.json", "cli-results.json"],
  ["objects-2.json", "cli-results-2.json"],
];

// "path=3992205037/api=apps/v1/shop/Deployment/priv-app" -> "api=apps/v1/shop/Deployment/priv-app"
const stripPath = (id) => String(id).replace(/^path=\d+\//, "");

let checks = 0, failures = 0;
const fail = (msg) => { failures++; console.error("  MISMATCH " + msg); };
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

for (const [objFile, cliFile] of CASES) {
  const objects = JSON.parse(readFileSync(path.join(FIX, objFile), "utf8"));
  const cli = JSON.parse(readFileSync(path.join(FIX, cliFile), "utf8"));
  const nano = JSON.parse(globalThis.__vyomi_kubescape_eval(JSON.stringify(objects)));
  console.log(`case ${objFile} (${objects.length} objects) vs ${cliFile}`);

  const failedSet = (report, cid) => {
    const s = new Set();
    for (const r of report.results || [])
      for (const c of r.controls || [])
        if (c.controlID === cid && (c.status?.status) === "failed") s.add(stripPath(r.resourceID));
    return [...s].sort();
  };
  const statusSet = (report, cid) => {
    const m = {};
    for (const r of report.results || [])
      for (const c of r.controls || [])
        if (c.controlID === cid) m[stripPath(r.resourceID)] = c.status?.status + (c.status?.subStatus ? "/" + c.status.subStatus : "");
    return Object.keys(m).sort().map((k) => k + "=" + m[k]);
  };

  // remediation paths (fix/review/delete) per failed resource, as the report lists them (the CLI's
  // Go struct always serialises an empty fixPath next to a deletePath/reviewPath, so those win)
  const pathSet = (report, cid) => {
    const out = [];
    for (const r of report.results || [])
      for (const c of r.controls || [])
        if (c.controlID === cid)
          for (const ru of c.rules || [])
            for (const p of ru.paths || [])
              out.push([stripPath(r.resourceID), ru.name, p.deletePath ? "delete:" + p.deletePath : p.reviewPath ? "review:" + p.reviewPath : p.fixPath && p.fixPath.path ? "fix:" + p.fixPath.path + "=" + p.fixPath.value : "cmd:" + p.fixCommand].join(" "));
    return out.sort();
  };

  for (const cid of info.controls) {
    const cs = cli.summaryDetails.controls[cid];
    const ns = nano.summaryDetails.controls[cid];
    if (!cs) { fail(`${cid}: not in the CLI report`); continue; }
    const cnt = (s) => [s.ResourceCounters.failedResources, s.ResourceCounters.passedResources, s.ResourceCounters.excludedResources || 0];
    checks++; if (!eq(cnt(cs), cnt(ns))) fail(`${cid} counts [failed,passed,excluded] cli=${cnt(cs)} nano=${cnt(ns)}`);
    checks++; if (cs.status !== ns.status) fail(`${cid} status cli=${cs.status} nano=${ns.status}`);
    checks++; if (cs.severity !== ns.severity) fail(`${cid} severity cli=${cs.severity} nano=${ns.severity}`);
    const cf = failedSet(cli, cid), nf = failedSet(nano, cid);
    checks++; if (!eq(cf, nf)) fail(`${cid} failed resources\n    cli =${JSON.stringify(cf)}\n    nano=${JSON.stringify(nf)}`);
    const cst = statusSet(cli, cid), nst = statusSet(nano, cid);
    checks++; if (!eq(cst, nst)) fail(`${cid} per-resource status\n    cli =${JSON.stringify(cst)}\n    nano=${JSON.stringify(nst)}`);
    const cp = pathSet(cli, cid), np = pathSet(nano, cid);
    checks++; if (!eq(cp, np)) fail(`${cid} remediation paths\n    cli =${JSON.stringify(cp)}\n    nano=${JSON.stringify(np)}`);
  }
}

console.log(`${info.controls.length} controls included, ${checks - failures} of ${checks} parity checks passed`);
process.exit(failures ? 1 : 0);
