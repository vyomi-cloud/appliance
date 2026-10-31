/* Vyomi Nano — in-browser Kubescape evaluator (OPA compiled to WebAssembly).
 *
 * Kubescape (Go) cannot run in Pyodide, but its controls are Rego (kubescape/regolibrary,
 * Apache-2.0). build_kubescape_wasm.py compiles the file-scannable controls whose rules are
 * self-contained into policy.wasm; this module evaluates them over a cluster's Kubernetes
 * objects the way Kubescape's opaprocessor does (rule match -> input array, posture control
 * inputs as data, failed = alertObject.k8sApiObjects, passed = every other matched input,
 * default system exceptions), and returns a subset of the Kubescape CLI JSON report — so the
 * Python mapper reads Nano results and real CLI results the same way.
 * Parity with the real CLI is asserted by tests/conformance/test_kubescape_wasm_parity.mjs.
 *
 * Usage (page, module worker, or Node):
 *   import { installKubescape } from "<base>/kubescape/ks-eval.mjs";
 *   await installKubescape("<base>/kubescape/");          // fetches controls.json + policy.wasm
 *   globalThis.__vyomi_kubescape_eval(JSON.stringify(objects)) -> JSON string (synchronous)
 * Node/tests can pass the bytes directly: installKubescape(null, { controls, wasm }).
 */
import opa from "./lib/opa-wasm.mjs";

const SEVERITY_ORDER = ["Unknown", "Low", "Medium", "High", "Critical"];

function splitApiVersion(apiVersion) {
  const av = String(apiVersion || "");
  const i = av.indexOf("/");
  return i === -1 ? ["", av] : [av.slice(0, i), av.slice(i + 1)];
}

// k8sinterface-style plural resource name, only used to order the input like Kubescape's
// sorted GVR index (rule verdicts don't depend on it).
function plural(kind) {
  const k = String(kind || "").toLowerCase();
  if (/(s|x|z|ch|sh)$/.test(k)) return k + "es";
  if (/[^aeiou]y$/.test(k)) return k.slice(0, -1) + "ies";
  return k + "s";
}

/** The CLI's resource id without the file `path=<hash>/` prefix. */
export function resourceId(obj) {
  const [group, version] = splitApiVersion(obj && obj.apiVersion);
  const md = (obj && obj.metadata) || {};
  return `api=${group}/${version}/${md.namespace || ""}/${obj && obj.kind}/${md.name || ""}`;
}

function regexFull(pattern, value, flags = "") {
  try { return new RegExp("^(?:" + pattern + ")$", flags).test(String(value ?? "")); } catch (_) { return false; }
}

// Kubescape's default posture exceptions (artifacts exceptions.json), opa-utils exceptions
// processor semantics for the designator kinds those exceptions use.
function exceptionMatches(exc, obj, controlID, ruleName) {
  const pols = exc.posturePolicies || [];
  if (pols.length) {
    const ok = pols.some((p) =>
      (!p.controlID || p.controlID.toLowerCase() === controlID.toLowerCase() || regexFull(p.controlID, controlID, "i")) &&
      (!p.ruleName || p.ruleName.toLowerCase() === ruleName.toLowerCase() || regexFull(p.ruleName, ruleName, "i")));
    if (!ok) return false;
  }
  const md = obj.metadata || {};
  const designators = exc.resources || [];
  if (!designators.length) return true;
  return designators.some((d) => {
    const at = { ...(d.attributes || {}) };
    const cluster = at.cluster; delete at.cluster;
    if (cluster) return false;                       // file / cluster-less scans have no cluster name
    const { namespace, kind, name, resourceID, path } = at;
    delete at.namespace; delete at.kind; delete at.name; delete at.resourceID; delete at.path;
    if (namespace === undefined && kind === undefined && name === undefined && resourceID === undefined && path === undefined && !Object.keys(at).length) return false;
    if (namespace !== undefined && namespace !== "" && !regexFull(namespace, obj.kind === "Namespace" ? md.name : md.namespace)) return false;
    if (kind !== undefined && kind !== "" && !regexFull(kind, obj.kind)) return false;
    if ("apiGroup" in at) { if (!regexFull(at.apiGroup, splitApiVersion(obj.apiVersion)[0])) return false; delete at.apiGroup; }
    if (name !== undefined && name !== "" && !regexFull(name, md.name)) return false;
    if (resourceID) return false;                    // ids differ from the cluster's; none of the defaults use it
    if (path) return false;                          // no sourcePath on cluster objects
    const container = at.containerName; delete at.containerName;
    if (Object.keys(at).length) {
      const cmp = (m) => m && Object.keys(m).length && Object.entries(at).every(([k, v]) => k in m && regexFull(v, m[k]));
      if (!cmp(md.labels) && !cmp(md.annotations)) return false;
    }
    if (container !== undefined) {
      const spec = obj.kind === "Pod" ? obj.spec : obj.kind === "CronJob" ? obj.spec?.jobTemplate?.spec?.template?.spec : obj.spec?.template?.spec;
      const names = [...(spec?.containers || []), ...(spec?.initContainers || [])].map((c) => c.name);
      if (!names.some((n) => regexFull(container, n))) return false;
    }
    return true;
  });
}

function buildEvaluator(meta, policy) {
  const rules = meta.rules;
  const inputs = meta.controlsInputs || {};
  const exceptions = meta.exceptions || [];

  function ruleData(rule) {
    const pci = {};
    for (const p of rule.configInputs || []) {
      const parts = String(p).split(".");
      if (parts.length !== 3) continue;
      const v = inputs[parts[2]];
      if (v !== undefined && v !== null) pci[parts[2]] = v;
    }
    return { postureControlInputs: pci, dataControlInputs: { cloudProvider: "" } };
  }

  function index(objects) {
    // GVR-keyed groups sorted by key, objects in load order (Kubescape's resourceGroupIndex)
    const groups = new Map();
    objects.forEach((o, ordinal) => {
      if (!o || typeof o !== "object" || !o.kind) return;
      const [g, v] = splitApiVersion(o.apiVersion);
      const key = `${g}/${v}/${plural(o.kind)}`;
      if (!groups.has(key)) groups.set(key, { group: g, version: v, resource: plural(o.kind), objects: [] });
      groups.get(key).objects.push({ o, ordinal });
    });
    return [...groups.keys()].sort().map((k) => groups.get(k));
  }

  const mv = (p, v) => p === "*" || p === v || (p === "core" && v === "");

  function matched(idx, match) {
    const out = [], emitted = new Set();
    for (const m of match || [])
      for (const g of m.apiGroups || []) for (const v of m.apiVersions || []) for (const r of m.resources || [])
        for (const grp of idx) {
          if (!mv(g, grp.group) || !mv(v, grp.version)) continue;
          const direct = r === "*" || r.toLowerCase() === grp.resource;
          for (const { o, ordinal } of grp.objects) {
            if (emitted.has(ordinal)) continue;
            if (!direct && r.toLowerCase() !== String(o.kind).toLowerCase()) continue;
            out.push(o); emitted.add(ordinal);
          }
        }
    return out;
  }

  function runRule(n, input) {
    const rule = rules[n];
    policy.setData(ruleData(rule));
    const res = policy.evaluate(input, rule.entrypoint);
    const deny = (res && res[0] && res[0].result) || [];
    return Array.isArray(deny) ? deny : [];
  }

  return function evaluate(objects) {
    const idx = index(objects);
    const perRule = new Map();                     // rule index -> {failed: Map(id -> {obj, paths}), passed: Set(id), objs}
    const ruleResult = (n) => {
      if (perRule.has(n)) return perRule.get(n);
      const input = matched(idx, rules[n].match);
      const r = { failed: new Map(), passed: new Map(), error: null };
      if (input.length) {
        let responses = [];
        try { responses = runRule(n, input); } catch (e) { r.error = String(e && e.message || e); }
        if (!r.error) {
          for (const resp of responses) {
            if (resp && resp.exception) continue;
            const objs = [...(resp?.alertObject?.k8sApiObjects || [])];
            if (resp?.alertObject?.externalObjects) objs.push(resp.alertObject.externalObjects);
            for (const fo of objs) {
              const id = resourceId(fo);
              if (!r.failed.has(id)) r.failed.set(id, { obj: fo, paths: [] });
              const paths = r.failed.get(id).paths;
              for (const p of resp.deletePaths || []) paths.push({ resourceID: id, deletePath: p });
              for (const p of resp.reviewPaths || []) paths.push({ resourceID: id, reviewPath: p });
              for (const p of resp.fixPaths || []) paths.push({ resourceID: id, fixPath: p });
              if (resp.fixCommand) paths.push({ resourceID: id, fixCommand: resp.fixCommand });
              for (const rel of resp.relatedObjects || []) {
                const rid = resourceId(rel.object || {});
                for (const p of rel.deletePaths || []) paths.push({ resourceID: rid, deletePath: p });
                for (const p of rel.reviewPaths || []) paths.push({ resourceID: rid, reviewPath: p });
                for (const p of rel.fixPaths || []) paths.push({ resourceID: rid, fixPath: p });
              }
            }
          }
          for (const o of input) { const id = resourceId(o); if (!r.failed.has(id)) r.passed.set(id, o); }
        }
      }
      perRule.set(n, r);
      return r;
    };

    const results = new Map();                     // resourceID -> {resourceID, controls: []}
    const summary = {};
    for (const c of meta.controls) {
      const byRes = new Map();                     // id -> {obj, rules: [...]}
      let skipped = false;
      for (const n of c.rules) {
        const r = ruleResult(n);
        const name = rules[n].name;
        if (r.error) { skipped = true; continue; }
        for (const [id, f] of r.failed) {
          if (!byRes.has(id)) byRes.set(id, { obj: f.obj, rules: [] });
          const exc = exceptions.filter((e) => exceptionMatches(e, f.obj, c.controlID, name));
          // Kubescape v4.0.16 keeps an excepted resource FAILED and tags it w/exceptions
          // (it still counts as a failed resource) — measured against the CLI in case 2.
          byRes.get(id).rules.push(exc.length
            ? { name, status: "failed", subStatus: "w/exceptions", paths: f.paths, exception: exc.map((e) => e.name) }
            : { name, status: "failed", subStatus: "", paths: f.paths });
        }
        for (const [id, o] of r.passed) {
          if (!byRes.has(id)) byRes.set(id, { obj: o, rules: [] });
          byRes.get(id).rules.push({ name, status: "passed", subStatus: "" });
        }
      }
      let failed = 0, passed = 0;
      const excluded = 0;
      for (const [id, e] of byRes) {
        const anyFailed = e.rules.some((r) => r.status === "failed");
        const exc = anyFailed && e.rules.filter((r) => r.status === "failed").every((r) => r.subStatus === "w/exceptions");
        const status = anyFailed ? "failed" : "passed";
        if (anyFailed) failed++; else passed++;
        if (!results.has(id)) results.set(id, { resourceID: id, controls: [] });
        results.get(id).controls.push({
          controlID: c.controlID, name: c.name, severity: c.severity,
          status: exc ? { status, subStatus: "w/exceptions" } : { status },
          rules: e.rules.map((r) => ({ name: r.name, status: r.status, subStatus: r.subStatus, ...(r.paths ? { paths: r.paths } : {}), ...(r.exception ? { exceptions: r.exception } : {}) })),
        });
      }
      let status = failed ? "failed" : "passed", subStatus;
      if (!failed && !byRes.size) subStatus = "irrelevant";
      if (skipped && !byRes.size) { status = "skipped"; subStatus = "integration"; }
      summary[c.controlID] = {
        controlID: c.controlID, name: c.name, severity: c.severity, status,
        statusInfo: subStatus ? { status, subStatus } : { status },
        ResourceCounters: { passedResources: passed, failedResources: failed, skippedResources: 0, excludedResources: excluded },
        category: { name: c.category },
      };
    }
    return {
      summaryDetails: { controls: summary },
      results: [...results.values()],
      evaluator: "opa-wasm",
      kubescapeVersion: meta.version && meta.version.kubescape,
      controlsEvaluated: meta.controls.map((c) => c.controlID),
    };
  };
}

export async function installKubescape(baseUrl, opts = {}) {
  let meta = opts.controls, wasm = opts.wasm;
  if (!meta || !wasm) {
    const base = String(baseUrl || new URL(".", import.meta.url).href).replace(/\/?$/, "/");
    const [m, w] = await Promise.all([
      fetch(base + "controls.json").then((r) => { if (!r.ok) throw new Error("controls.json HTTP " + r.status); return r.json(); }),
      fetch(base + "policy.wasm").then((r) => { if (!r.ok) throw new Error("policy.wasm HTTP " + r.status); return r.arrayBuffer(); }),
    ]);
    meta = meta || m; wasm = wasm || w;
  }
  if (typeof meta === "string") meta = JSON.parse(meta);
  const policy = await opa.loadPolicy(wasm);
  const evaluate = buildEvaluator(meta, policy);
  globalThis.__vyomi_kubescape_eval = (objectsJson) => {
    const objects = typeof objectsJson === "string" ? JSON.parse(objectsJson) : objectsJson;
    return JSON.stringify(evaluate(Array.isArray(objects) ? objects : []));
  };
  globalThis.__vyomi_kubescape_info = {
    engine: "opa-wasm", kubescape: meta.version && meta.version.kubescape, opa: meta.version && meta.version.opa,
    frameworks: meta.version && meta.version.frameworks, controls: meta.controls.map((c) => c.controlID),
  };
  return globalThis.__vyomi_kubescape_info;
}

export { SEVERITY_ORDER };
