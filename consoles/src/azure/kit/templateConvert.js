// Client-side ARM template -> Bicep / Terraform (azapi) renderers used by every
// "Export template" blade. Pure functions over the template object the blade already built
// from the resource's real ARM properties; nothing is sent anywhere.
const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;
const PARAM_ONLY = /^\[parameters\('([^']+)'\)\]$/;

const bicepStr = (s) => "'" + String(s).replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/\n/g, "\\n").replace(/\$\{/g, "\\${") + "'";

function bicepVal(v, ind) {
  const pad = "  ".repeat(ind + 1), end = "  ".repeat(ind);
  if (v === null || v === undefined) return "null";
  if (typeof v === "string") {
    const m = PARAM_ONLY.exec(v);
    if (m) return m[1];
    if (/^\[.*\]$/.test(v) && !v.startsWith("[[")) return bicepStr(v);
    return bicepStr(v);
  }
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.length ? "[\n" + v.map((x) => pad + bicepVal(x, ind + 1)).join("\n") + "\n" + end + "]" : "[]";
  const ks = Object.keys(v);
  return ks.length ? "{\n" + ks.map((k) => `${pad}${IDENT.test(k) ? k : bicepStr(k)}: ${bicepVal(v[k], ind + 1)}`).join("\n") + "\n" + end + "}" : "{}";
}

const sym = (r, i) => (String(r.name || "res").replace(/\[parameters\('([^']+)'\)\]/, "$1").replace(/[^A-Za-z0-9]+/g, "_").replace(/^(\d)/, "_$1") || "res") + (i ? "_" + i : "");

export function armToBicep(t) {
  const out = [];
  for (const [n, p] of Object.entries(t.parameters || {}))
    out.push(`param ${n} ${String(p.type || "string").toLowerCase() === "object" ? "object" : "string"}${p.defaultValue !== undefined ? " = " + bicepVal(p.defaultValue, 0) : ""}`);
  if (out.length) out.push("");
  (t.resources || []).forEach((r, i) => {
    const { type, apiVersion, ...rest } = r;
    out.push(`resource ${sym(r, i)} '${type}@${apiVersion}' = ${bicepVal(rest, 0)}`, "");
  });
  return out.join("\n").trimEnd() + "\n";
}

function hclVal(v, ind) {
  const pad = "  ".repeat(ind + 1), end = "  ".repeat(ind);
  if (v === null || v === undefined) return "null";
  if (typeof v === "string") {
    const m = PARAM_ONLY.exec(v);
    if (m) return "var." + m[1];
    return JSON.stringify(v).replace(/\$\{/g, "$${").replace(/%\{/g, "%%{");
  }
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.length ? "[\n" + v.map((x) => pad + hclVal(x, ind + 1) + ",").join("\n") + "\n" + end + "]" : "[]";
  const ks = Object.keys(v);
  return ks.length ? "{\n" + ks.map((k) => `${pad}${IDENT.test(k) ? k : JSON.stringify(k)} = ${hclVal(v[k], ind + 1)}`).join("\n") + "\n" + end + "}" : "{}";
}

export function armToTerraform(t) {
  const out = ['terraform {', '  required_providers {', '    azapi = { source = "Azure/azapi" }', '  }', '}', '',
    'variable "resource_group_id" {', '  type        = string', '  description = "Resource id of the resource group that holds these resources"', '}', ''];
  for (const [n, p] of Object.entries(t.parameters || {})) {
    const obj = String(p.type || "string").toLowerCase() === "object";
    out.push(`variable "${n}" {`, `  type    = ${obj ? "map(string)" : "string"}`, ...(p.defaultValue !== undefined ? [`  default = ${hclVal(p.defaultValue, 1)}`] : []), "}", "");
  }
  (t.resources || []).forEach((r, i) => {
    const { type, apiVersion, name, location, ...rest } = r;
    out.push(`resource "azapi_resource" "${sym(r, i)}" {`, `  type      = "${type}@${apiVersion}"`, `  name      = ${hclVal(name, 1)}`,
      ...(location ? [`  location  = ${hclVal(location, 1)}`] : []), "  parent_id = var.resource_group_id",
      `  body = ${hclVal(rest, 1)}`, "}", "");
  });
  return out.join("\n").trimEnd() + "\n";
}

export function convertTemplate(kind, t) {
  return kind === "bicep" ? armToBicep(t) : kind === "terraform" ? armToTerraform(t) : JSON.stringify(t, null, 2);
}
