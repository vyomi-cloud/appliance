/* UI-conformance fixtures for Function Apps — native-wire setup run by
 * consoles/tests/ui-conformance.mjs. Each returns the text the page must then show
 * (liveness: proves the page is not static). `wire(method, path, {svc:null})` sends an
 * un-signed native ARM request (Azure carries no SigV4). */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const base = (name, tail = "") => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Web/sites/${name}${tail}`;
const q = "?api-version=2023-12-01";

async function ensureSite(wire, name) {
  await wire("PUT", base(name) + q, { svc: null, body: { location: "eastus", kind: "functionapp", properties: { reserved: true, siteConfig: { _runtime: "Python", _version: "3.12" } } } });
  return name;
}

export default {
  "az-functionapp": async (wire) => ensureSite(wire, "uicfn"),
  "site": async (wire, uniq = "uic") => ensureSite(wire, `${uniq}fn`),
  "function": async (wire, uniq = "uic") => {
    await ensureSite(wire, "uicfn");
    const name = `${uniq}trigger`;
    await wire("PUT", base("uicfn", `/functions/${name}`) + q, { svc: null, body: { properties: { entryPoint: "main", files: { "__init__.py": "def main(req):\n    return {'ok': True}\n" }, config: { bindings: [{ authLevel: "function", type: "httpTrigger", direction: "in", name: "req", methods: ["get", "post"] }] } } } });
    return name;
  },
  "appsetting": async (wire, uniq = "uic") => {
    await ensureSite(wire, "uicfn");
    const key = `UIC_${uniq.toUpperCase()}`;
    const current = (await wire("POST", base("uicfn", "/config/appsettings") + q, { svc: null, body: {} })).properties || {};
    await wire("PUT", base("uicfn", "/config/appsettings") + q, { svc: null, body: { properties: { ...current, [key]: "1" } } });
    return key;
  },
  "hostkey": async (wire, uniq = "uic") => {
    await ensureSite(wire, "uicfn");
    const name = `uickey${uniq}`;
    await wire("PUT", base("uicfn", `/host/default/functionkeys/${name}`) + q, { svc: null, body: {} });
    return name;
  },
  // CanNotDelete, not ReadOnly — these locks are never removed (each run adds another one with
  // a fresh unique name), and uicfn is the one shared site every other page's fixture re-PUTs;
  // a ReadOnly lock would permanently block those writes now that locks are enforced.
  "lock": async (wire, uniq = "uic") => {
    await ensureSite(wire, "uicfn");
    const name = `uiclock${uniq}`;
    await wire("PUT", base("uicfn", `/locks/${name}`) + q, { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return name;
  },
  "activity": async (wire, uniq = "uic") => {
    await ensureSite(wire, "uicfn");
    const name = `uicact${uniq}`;
    await wire("PUT", base("uicfn", `/locks/${name}`) + q, { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return name;
  },
};
