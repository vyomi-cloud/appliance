/* CEL subset for IAM Conditions: a JS mirror of core/iam_engine/gcp_eval.py (_tokenize/_P grammar, the has/timestamp/duration/size/string/int/double
 * functions and the startsWith/endsWith/contains/matches/size + timestamp accessor methods). validateCel() reports what the engine would refuse
 * (CelUnsupported) so the editor shows the same verdict the evaluator would give. The builder <-> expression sync lives here too. */
const TOK = /\s*(?:(\d+\.\d+(?:[eE][+-]?\d+)?|\d+)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|([A-Za-z_][A-Za-z_0-9]*)|(\|\||&&|==|!=|<=|>=|[<>!+\-*/%()\[\].,?:{}]))/y;
const FNS = new Set(["has", "timestamp", "duration", "size", "string", "int", "double"]);
const METHODS = new Set(["startsWith", "endsWith", "contains", "matches", "size", "getFullYear", "getMonth", "getDate", "getDayOfMonth", "getDayOfWeek", "getDayOfYear", "getHours", "getMinutes", "getSeconds", "getMilliseconds"]);
const VARS = new Set(["request", "resource", "api"]);

export function tokenize(s) {
  const out = []; let pos = 0; s = s.replace(/\s+$/, "");
  while (pos < s.length) {
    TOK.lastIndex = pos; const m = TOK.exec(s);
    if (!m) throw new Error(`unexpected character at ${pos}: ${JSON.stringify(s.slice(pos, pos + 8))}`);
    pos = TOK.lastIndex;
    out.push(m[1] != null ? ["num", m[1]] : m[2] != null ? ["str", m[2]] : m[3] != null ? ["id", m[3]] : ["op", m[4]]);
  }
  return out;
}

/** -> {ok:true} | {ok:false, error}. Syntax + function/method allow-list + known root variables. */
export function validateCel(expr) {
  if (!String(expr || "").trim()) return { ok: false, error: "Expression is empty" };
  let t, i = 0;
  try { t = tokenize(expr); } catch (e) { return { ok: false, error: e.message }; }
  const peek = () => t[i] || [null, null];
  const take = (v) => { const k = peek(); if (k[0] === null || (v != null && k[1] !== v)) throw new Error(`expected ${v ?? "token"} but found ${k[1] ?? "end of expression"}`); i++; return k; };
  const accept = (v) => { const k = peek(); if (k[1] === v && (k[0] === "op" || k[0] === "id")) { i++; return true; } return false; };
  const args = () => { if (accept(")")) return; for (;;) { ternary(); if (accept(")")) return; take(","); } };
  const ternary = () => { or(); if (accept("?")) { ternary(); take(":"); ternary(); } };
  const bin = (next, ops) => () => { next(); for (;;) { const k = peek(); if (k[0] === "op" && ops.includes(k[1]) || (k[0] === "id" && k[1] === "in" && ops.includes("in"))) { i++; next(); } else return; } };
  let unary;
  const postfix = () => {
    primary();
    for (;;) {
      if (accept(".")) { const n = take()[1]; if (accept("(")) { if (!METHODS.has(n)) throw new Error(`method ${n}() not supported`); args(); } }
      else if (accept("[")) { ternary(); take("]"); } else return;
    }
  };
  const primary = () => {
    const [k, v] = peek(); if (k === null) throw new Error("unexpected end of expression"); i++;
    if (k === "num" || k === "str") return;
    if (k === "op" && v === "(") { ternary(); take(")"); return; }
    if (k === "op" && v === "[") { if (!accept("]")) for (;;) { ternary(); if (accept("]")) break; take(","); } return; }
    if (k === "id") {
      if (["true", "false", "null"].includes(v)) return;
      if (accept("(")) { if (!FNS.has(v)) throw new Error(`function ${v}() not supported`); args(); return; }
      if (!VARS.has(v)) throw new Error(`undeclared reference to '${v}' (use request, resource or api)`);
      return;
    }
    throw new Error(`unexpected token ${v}`);
  };
  unary = () => { if (accept("!")) return unary(); if (peek()[1] === "-" && peek()[0] === "op") { i++; return unary(); } postfix(); };
  const mul = bin(unary, ["*", "/", "%"]), add = bin(mul, ["+", "-"]), rel = bin(add, ["==", "!=", "<", "<=", ">", ">=", "in"]);
  const and = bin(rel, ["&&"]); const or = bin(and, ["||"]);
  try { ternary(); if (i !== t.length) throw new Error(`unexpected ${peek()[1]}`); } catch (e) { return { ok: false, error: e.message }; }
  return { ok: true };
}

// ── builder model ────────────────────────────────────────────────────────────────────────
export const COND_TYPES = [
  ["Time", [["expiry", "Expiry"], ["schedule", "Schedule"]]],
  ["Resource", [["type", "Type"], ["name", "Name"], ["service", "Service"]]],
];
export const NAME_OPS = [["eq", "is"], ["ne", "is not"], ["starts", "starts with"], ["ends", "ends with"], ["contains", "contains"]];
export const SET_OPS = [["eq", "is"], ["ne", "is not"]];
const q = (s) => JSON.stringify(String(s));
const iso = (v) => { const d = new Date(v); return isNaN(d) ? "" : d.toISOString(); };

/** One builder row -> CEL atom ("" while incomplete). Row: {kind, op?, value?, start?, end?}. */
export function atom(r) {
  if (r.kind === "expiry") { const t = iso(r.end); return t ? `request.time < timestamp(${q(t)})` : ""; }
  if (r.kind === "schedule") { const a = iso(r.start), b = iso(r.end); return a && b ? `request.time >= timestamp(${q(a)}) && request.time < timestamp(${q(b)})` : ""; }
  const f = r.kind === "type" ? "resource.type" : r.kind === "service" ? "resource.service" : r.kind === "name" ? "resource.name" : "";
  if (!f || !r.value) return "";
  const v = q(r.value);
  switch (r.op || "eq") { case "ne": return `${f} != ${v}`; case "starts": return `${f}.startsWith(${v})`; case "ends": return `${f}.endsWith(${v})`; case "contains": return `${f}.contains(${v})`; default: return `${f} == ${v}`; }
}
/** rows -> expression. A row with join:"or" starts a new OR group; rows inside a group are AND-ed. */
export function rowsToCel(rows) {
  const groups = [];
  rows.forEach((r, i) => { const a = atom(r); if (!a) return; if (i === 0 || r.join === "or" || !groups.length) groups.push([a]); else groups[groups.length - 1].push(a); });
  const parts = groups.map((g) => g.join(" && "));
  return parts.length > 1 ? groups.map((g) => (g.length > 1 ? `(${g.join(" && ")})` : g[0])).join(" || ") : parts[0] || "";
}

function splitTop(s, sep) {
  const out = []; let depth = 0, quote = null, cur = "";
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (quote) { cur += c; if (c === "\\") { cur += s[++i] ?? ""; } else if (c === quote) quote = null; continue; }
    if (c === '"' || c === "'") { quote = c; cur += c; continue; }
    if (c === "(") depth++; if (c === ")") depth--;
    if (!depth && s.startsWith(sep, i)) { out.push(cur); cur = ""; i += sep.length - 1; continue; }
    cur += c;
  }
  out.push(cur); return out.map((x) => x.trim());
}
const wrapped = (g) => { let d = 0, q = null; for (let i = 0; i < g.length; i++) { const c = g[i]; if (q) { if (c === "\\") i++; else if (c === q) q = null; continue; } if (c === '"' || c === "'") q = c; else if (c === "(") d++; else if (c === ")" && --d === 0 && i < g.length - 1) return false; } return true; };
const unq = (t) => { try { return JSON.parse(t); } catch { return t.slice(1, -1); } };
const S = '("(?:[^"\\\\]|\\\\.)*")';
function parseAtom(a) {
  let m;
  if ((m = new RegExp(`^request\\.time < timestamp\\(${S}\\)$`).exec(a))) return { kind: "expiry", end: unq(m[1]) };
  if ((m = new RegExp(`^resource\\.(type|service|name) (==|!=) ${S}$`).exec(a))) return { kind: m[1], op: m[2] === "==" ? "eq" : "ne", value: unq(m[3]) };
  if ((m = new RegExp(`^resource\\.(name|type|service)\\.(startsWith|endsWith|contains)\\(${S}\\)$`).exec(a))) return { kind: m[1], op: { startsWith: "starts", endsWith: "ends", contains: "contains" }[m[2]], value: unq(m[3]) };
  return null;
}
/** expression -> rows, or null when it uses something the builder cannot express (the real console then shows the editor only). */
export function celToRows(expr) {
  const e = String(expr || "").trim(); if (!e) return [];
  const rows = [];
  for (const [gi, g] of splitTop(e, "||").entries()) {
    const inner = g.startsWith("(") && g.endsWith(")") && splitTop(g.slice(1, -1) + " ", "&&").length >= 1 && wrapped(g) ? g.slice(1, -1) : g;
    const atoms = splitTop(inner, "&&");
    // schedule = request.time >= timestamp(a) && request.time < timestamp(b)
    for (let i = 0; i < atoms.length; i++) {
      const join = rows.length && i === 0 && gi > 0 ? "or" : undefined;
      let m;
      if ((m = new RegExp(`^request\\.time >= timestamp\\(${S}\\)$`).exec(atoms[i])) && atoms[i + 1]) {
        const n = new RegExp(`^request\\.time < timestamp\\(${S}\\)$`).exec(atoms[i + 1]);
        if (n) { rows.push({ kind: "schedule", start: unq(m[1]), end: unq(n[1]), join }); i++; continue; }
      }
      const r = parseAtom(atoms[i]); if (!r) return null;
      rows.push({ ...r, join });
    }
  }
  return rows;
}
