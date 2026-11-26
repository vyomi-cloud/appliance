/* Pure IAM-policy helpers for the AWS pickers (no React, no DOM: unit-tested under node).
 * Everything that names an action, resource type or condition key comes from the verbatim service-reference catalog
 * (core/iam_catalog/aws/<svc>.json: actions{Name:{l,r[],k[]}}, resources{type:[arn templates]}, conditionKeys{key:type}). */

export const LEVELS = [["list", "List"], ["read", "Read"], ["write", "Write"], ["permissions", "Permissions management"], ["tagging", "Tagging"]];
export const LEVEL_ALL_LABEL = { list: "All list actions", read: "All read actions", write: "All write actions", permissions: "All permissions management actions", tagging: "All tagging actions" };

export const actionNames = (cat) => Object.keys(cat?.actions || {});
export const byLevel = (cat, level, filter = "") => {
  const f = filter.trim().toLowerCase();
  return actionNames(cat).filter((n) => cat.actions[n].l === level && (!f || n.toLowerCase().includes(f))).sort();
};

/** Resource types a set of actions applies to (catalog `r`); "*" = at least one action takes no resource type. */
export function resourceTypesFor(cat, names) {
  const types = []; let star = false;
  for (const n of names) {
    const r = cat.actions[n]?.r || [];
    if (!r.length) star = true;
    for (const t of r) if (!types.includes(t)) types.push(t);
  }
  types.sort();
  return star ? [...types, "*"] : types;
}
export const actionsForType = (cat, names, type) => names.filter((n) => type === "*" ? !(cat.actions[n]?.r || []).length : (cat.actions[n]?.r || []).includes(type));

/** First ARN template of a resource type, with placeholders filled for a specific entry. */
export const arnTemplate = (cat, type) => (cat?.resources?.[type] || [])[0] || "";
export function anyInAccountArn(cat, type, account = "*") {
  const t = arnTemplate(cat, type);
  return t.replace(/\$\{Partition\}/g, "aws").replace(/\$\{Region\}/g, "*").replace(/\$\{Account\}/g, account).replace(/\$\{[^}]+\}/g, "*");
}
/** Does `arn` look like an instance of the type's templates? */
export function arnMatchesType(cat, type, arn) {
  return (cat?.resources?.[type] || []).some((t) => new RegExp("^" + t.split(/(\$\{[^}]+\})/).map((p) => /^\$\{/.test(p) ? ".*" : p.replace(/[.*+?^$()|[\]\\{}]/g, "\\$&")).join("") + "$").test(arn));
}

/** Expand an action pattern (`s3:Get*`, `s3:*`, `s3:GetObject`) against catalogs {prefix: cat}. null = unknown service (catalog not loaded / absent). */
export function expandAction(pattern, cats) {
  const i = pattern.indexOf(":");
  if (i < 0) return { service: null, matches: [], unknownService: true };
  const svc = pattern.slice(0, i), name = pattern.slice(i + 1);
  const cat = cats[svc];
  if (!cat) return { service: svc, matches: null, unknownService: true };
  const re = new RegExp("^" + name.split("*").map((p) => p.split("?").map((q) => q.replace(/[.+^$()|[\]\\{}]/g, "\\$&")).join(".")).join(".*") + "$", "i");
  return { service: svc, matches: actionNames(cat).filter((a) => re.test(a)) };
}

const opsFor = (type) => ({
  String: ["StringEquals", "StringLike", "StringNotEquals", "StringNotLike"],
  ArrayOfString: ["ForAnyValue:StringEquals", "ForAllValues:StringEquals", "ForAnyValue:StringLike"],
  ARN: ["ArnLike", "ArnEquals", "ArnNotLike"],
  ArrayOfARN: ["ForAnyValue:ArnLike", "ForAllValues:ArnLike"],
  Numeric: ["NumericEquals", "NumericLessThan", "NumericGreaterThan", "NumericLessThanEquals", "NumericGreaterThanEquals"],
  Bool: ["Bool"], ArrayOfBool: ["ForAnyValue:Bool"],
  Date: ["DateGreaterThan", "DateLessThan", "DateEquals"],
}[type] || ["StringEquals"]);
export const conditionOperators = opsFor;

export const GLOBAL_COND_KEYS = { "aws:MultiFactorAuthPresent": "Bool", "aws:SourceIp": "String", "aws:RequestedRegion": "String", "aws:PrincipalArn": "ARN", "aws:SecureTransport": "Bool", "aws:CurrentTime": "Date", "aws:PrincipalOrgID": "String", "aws:username": "String" };
/** Condition keys offered for a statement: the keys the chosen actions support (catalog `k`), else all of the service's keys. */
export function conditionKeysFor(cat, names) {
  const keys = new Set();
  for (const n of names) for (const k of cat.actions[n]?.k || []) keys.add(k);
  const all = Object.keys(cat.conditionKeys || {});
  const list = (keys.size ? all.filter((k) => keys.has(k)) : all);
  return list.map((k) => ({ key: k, type: cat.conditionKeys[k] || "String" }));
}

export function newStatement(service = null) {
  return { id: Math.random().toString(36).slice(2, 9), service, effect: "Allow", allActions: false, actions: [], manual: [], resMode: "all", arns: {}, anyAcct: {}, anyRes: {}, mfa: false, ip: "", ipOn: false, conds: [], open: { actions: true, resources: false, conds: false } };
}

const uniq = (a) => [...new Set(a)];
export function statementActions(st) {
  return uniq([...(st.allActions ? [`${st.service}:*`] : st.actions.map((a) => `${st.service}:${a}`)), ...st.manual]);
}
/** Visual model -> IAM policy document. cats = {prefix: catalog}. */
export function statementsToPolicy(stmts, cats) {
  const Statement = [];
  stmts.forEach((st, i) => {
    if (!st.service) return;
    const cat = cats[st.service];
    const Action = statementActions(st);
    const out = { Sid: `Statement${i + 1}`, Effect: st.effect, Action: Action.length === 1 ? Action[0] : Action };
    let Resource = "*";
    if (st.resMode === "specific" && cat) {
      const names = st.allActions ? actionNames(cat) : st.actions;
      const arns = [];
      for (const t of resourceTypesFor(cat, names)) {
        if (t === "*") { arns.push("*"); continue; }
        if (st.anyRes[t]) { arns.push("*"); continue; }
        if (st.anyAcct[t]) arns.push(anyInAccountArn(cat, t));
        for (const a of st.arns[t] || []) arns.push(a);
      }
      Resource = arns.length ? uniq(arns) : "*";
      if (Array.isArray(Resource) && Resource.length === 1) Resource = Resource[0];
    }
    out.Resource = Resource;
    const Condition = {};
    const put = (op, key, val) => { (Condition[op] ||= {})[key] = val; };
    if (st.mfa) put("Bool", "aws:MultiFactorAuthPresent", "true");
    if (st.ipOn && st.ip) put("IpAddress", "aws:SourceIp", st.ip.includes(",") ? st.ip.split(",").map((s) => s.trim()) : st.ip);
    for (const c of st.conds) if (c.key && c.op) put(c.op, c.key, /^(Bool|ForAnyValue:Bool)$/.test(c.op) ? (c.value || "true") : c.value);
    if (Object.keys(Condition).length) out.Condition = Condition;
    Statement.push(out);
  });
  return { Version: "2012-10-17", Statement };
}

/** IAM policy document -> visual model (one visual statement per statement x service). Async: needs catalogs. Throws Error(reason) when the policy can't be shown visually. */
export async function policyToStatements(doc, loadCat) {
  const stmts = [];
  const list = Array.isArray(doc.Statement) ? doc.Statement : [doc.Statement];
  for (const s of list) {
    if (!s || typeof s !== "object") throw new Error("A statement is not an object");
    if (s.NotAction || s.NotResource || s.Principal || s.NotPrincipal) throw new Error("NotAction, NotResource and Principal statements can only be edited in the JSON editor");
    const acts = [].concat(s.Action || []);
    const ress = [].concat(s.Resource ?? []);
    const bySvc = {};
    for (const a of acts) { const svc = a.includes(":") ? a.split(":")[0] : null; if (!svc) throw new Error(`Action "${a}" has no service prefix`); (bySvc[svc] ||= []).push(a.slice(svc.length + 1)); }
    for (const [svc, names] of Object.entries(bySvc)) {
      const cat = await loadCat(svc);
      if (!cat) throw new Error(`No IAM catalog for service "${svc}"; edit in the JSON editor`);
      const st = newStatement(svc);
      st.effect = s.Effect === "Deny" ? "Deny" : "Allow";
      if (s.Sid) st.sid = s.Sid;
      for (const n of names) {
        if (n === "*") st.allActions = true;
        else if (cat.actions[n]) st.actions.push(n);
        else st.manual.push(`${svc}:${n}`);
      }
      const concrete = st.allActions ? actionNames(cat) : st.actions;
      if (!(ress.length === 1 && ress[0] === "*")) {
        st.resMode = "specific";
        const types = resourceTypesFor(cat, concrete);
        for (const r of ress) {
          const t = types.find((x) => x !== "*" && r === anyInAccountArn(cat, x));
          if (t) { st.anyAcct[t] = true; continue; }
          const m = types.find((x) => x !== "*" && arnMatchesType(cat, x, r));
          if (m) (st.arns[m] ||= []).push(r); else (st.arns[types.find((x) => x !== "*") || "*"] ||= []).push(r);
        }
      }
      for (const [op, kv] of Object.entries(s.Condition || {})) for (const [k, v] of Object.entries(kv)) {
        if (op === "Bool" && k === "aws:MultiFactorAuthPresent" && String(v) === "true") st.mfa = true;
        else if (op === "IpAddress" && k === "aws:SourceIp") { st.ipOn = true; st.ip = [].concat(v).join(", "); }
        else st.conds.push({ id: Math.random().toString(36).slice(2, 8), key: k, op, value: Array.isArray(v) ? v.join(",") : String(v) });
      }
      stmts.push(st);
    }
  }
  return stmts;
}

/** Validate a policy document (string or object) against the loaded catalogs. Returns lists of {message, path}. */
export function validatePolicy(input, cats) {
  const r = { security: [], errors: [], warnings: [], suggestions: [], expansions: [] };
  let doc = input;
  if (typeof input === "string") { try { doc = JSON.parse(input); } catch (e) { r.errors.push({ message: `Invalid JSON: ${e.message}` }); return r; } }
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) { r.errors.push({ message: "The policy document must be a JSON object." }); return r; }
  if (doc.Version && !["2012-10-17", "2008-10-17"].includes(doc.Version)) r.errors.push({ message: `Invalid policy version "${doc.Version}". Use "2012-10-17".` });
  if (!doc.Version) r.warnings.push({ message: 'Missing "Version". Add "Version": "2012-10-17" so policy variables work.' });
  if (!doc.Statement) { r.errors.push({ message: 'Missing required element "Statement".' }); return r; }
  const stmts = Array.isArray(doc.Statement) ? doc.Statement : [doc.Statement];
  stmts.forEach((s, i) => {
    const at = `Statement[${i}]`;
    if (!s || typeof s !== "object") { r.errors.push({ message: `${at} is not an object.`, path: at }); return; }
    if (!["Allow", "Deny"].includes(s.Effect)) r.errors.push({ message: `${at}: Effect must be "Allow" or "Deny".`, path: at });
    const acts = [].concat(s.Action ?? s.NotAction ?? []);
    if (!acts.length) r.errors.push({ message: `${at}: missing Action or NotAction.`, path: at });
    if (s.Resource === undefined && s.NotResource === undefined && !s.Principal) r.errors.push({ message: `${at}: missing Resource or NotResource.`, path: at });
    for (const a of acts) {
      if (typeof a !== "string") { r.errors.push({ message: `${at}: action ${JSON.stringify(a)} is not a string.` }); continue; }
      if (a === "*") { r.security.push({ message: `${at}: "*" allows every action.` }); continue; }
      const x = expandAction(a, cats);
      if (x.unknownService && x.matches === null) continue; // catalog not loaded / not modelled: cannot judge
      if (x.unknownService) { r.errors.push({ message: `${at}: "${a}" is not a valid action; use <service>:<Action>.` }); continue; }
      if (!x.matches.length) r.errors.push({ message: `${at}: the action "${a}" does not exist in the ${cats[x.service].name} service.`, action: a });
      else if (a.includes("*") || a.includes("?")) r.expansions.push({ pattern: a, count: x.matches.length });
    }
    if ([].concat(s.Action || []).includes("*") || [].concat(s.Action || []).some((a) => /^[a-z0-9-]+:\*$/.test(a))) r.warnings.push({ message: `${at}: wildcard action grants every action of the service.` });
    if (s.Effect === "Allow" && [].concat(s.Resource || []).includes("*")) r.suggestions.push({ message: `${at}: Resource "*" applies to all resources; restrict to specific ARNs where possible.` });
  });
  return r;
}
