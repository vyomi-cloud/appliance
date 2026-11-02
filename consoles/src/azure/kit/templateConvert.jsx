/* ARM template -> Bicep / Terraform (azapi) text, generated client-side from the resource's
 * live ARM JSON. Bicep is a 1:1 syntax rendering of the ARM resource; Terraform uses the
 * provider-agnostic azapi_resource (type@api-version + body) so it is valid for every type. */
import { CapabilityContainer } from "./Capability.jsx";
const STRIP = new Set(["provisioningState", "id", "etag", "systemData", "type"]);
const ident = (s) => String(s).replace(/[^a-zA-Z0-9_]/g, "_").replace(/^(\d)/, "_$1");
const isIdent = (k) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(k);

function clean(v, top) {
  if (Array.isArray(v)) return v.map((x) => clean(x));
  if (v && typeof v === "object") {
    const o = {};
    for (const [k, x] of Object.entries(v)) { if (top && STRIP.has(k)) continue; if (x === null || x === undefined) continue; o[k] = clean(x); }
    return o;
  }
  return v;
}
const bStr = (s) => (String(s).startsWith("[") && String(s).endsWith("]") && !String(s).startsWith("[[")
  ? String(s).slice(1, -1) : `'${String(s).replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`);

export function toBicepValue(v, ind = 0) {
  const pad = "  ".repeat(ind + 1), end = "  ".repeat(ind);
  if (Array.isArray(v)) return v.length ? `[\n${v.map((x) => pad + toBicepValue(x, ind + 1)).join("\n")}\n${end}]` : "[]";
  if (v && typeof v === "object") {
    const e = Object.entries(v);
    return e.length ? `{\n${e.map(([k, x]) => `${pad}${isIdent(k) ? k : `'${k}'`}: ${toBicepValue(x, ind + 1)}`).join("\n")}\n${end}}` : "{}";
  }
  return typeof v === "string" ? bStr(v) : String(v);
}
export function toHcl(v, ind = 0) {
  const pad = "  ".repeat(ind + 1), end = "  ".repeat(ind);
  if (Array.isArray(v)) return v.length ? `[\n${v.map((x) => pad + toHcl(x, ind + 1)).join(",\n")}\n${end}]` : "[]";
  if (v && typeof v === "object") {
    const e = Object.entries(v);
    return e.length ? `{\n${e.map(([k, x]) => `${pad}${isIdent(k) ? k : JSON.stringify(k)} = ${toHcl(x, ind + 1)}`).join("\n")}\n${end}}` : "{}";
  }
  return typeof v === "string" ? JSON.stringify(v) : String(v);
}

export function templateToBicep(t) {
  const params = Object.entries(t.parameters || {}).map(([k, p]) => `param ${k} ${p.type === "string" ? "string" : p.type}${p.defaultValue !== undefined ? ` = ${toBicepValue(p.defaultValue)}` : ""}\n`).join("");
  const res = (t.resources || []).map((r) => {
    const { type, apiVersion, dependsOn, ...rest } = r;
    const body = {};
    for (const [k, v] of Object.entries(rest)) body[k] = clean(v, false);
    return `resource ${ident(String(r.name).replace(/^\[parameters\('(.*)'\)\]$/, "$1"))} '${type}@${apiVersion}' = ${toBicepValue(body)}\n`;
  }).join("\n");
  return (params ? params + "\n" : "") + res;
}

export function templateToTerraform(t, rg) {
  const head = `terraform {\n  required_providers {\n    azapi = {\n      source = "Azure/azapi"\n    }\n  }\n}\n\n`;
  return head + (t.resources || []).map((r) => {
    const { type, apiVersion, name, location, tags, identity, kind, sku, properties } = r;
    const plain = String(name).replace(/^\[parameters\('(.*)'\)\]$/, "$1");
    const body = {};
    for (const [k, v] of Object.entries({ kind, sku, identity, properties })) if (v !== undefined) body[k] = clean(v, k === "properties");
    return `resource "azapi_resource" "${ident(plain)}" {\n  type      = "${type}@${apiVersion}"\n  name      = "${plain}"\n  parent_id = "/subscriptions/\${data.azurerm_client_config.current.subscription_id}/resourceGroups/${rg || "<resource-group>"}"\n${location ? `  location  = "${location}"\n` : ""}${tags && Object.keys(tags).length ? `  tags      = ${toHcl(tags, 1)}\n` : ""}  body = ${toHcl(body, 1)}\n}\n`;
  }).join("\n");
}

export function ConvertedTemplate({ template, format, rg, capId }) {
  const text = format === "bicep" ? templateToBicep(template) : templateToTerraform(template, rg);
  const title = format === "bicep" ? "Bicep" : "Terraform (azapi)";
  const pre = (
      <pre className="vy-mono" data-testid={`export-${format}`} style={{ maxHeight: 360, overflow: "auto", background: "var(--colorNeutralBackground3)", padding: 10, borderRadius: 4, fontSize: 12 }}>{text}</pre>
  );
  return capId ? <CapabilityContainer id={capId} title={title}>{pre}</CapabilityContainer> : <section className="vy-section"><h3>{title}</h3>{pre}</section>;
}
