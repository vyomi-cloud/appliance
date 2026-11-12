/* UI-conformance fixtures for Azure App Services — native ARM wire setup run by
 * consoles/tests/ui-conformance.mjs. Each returns the text the page must then show
 * (liveness: proves the page is not static). ARM requests carry no AWS signature
 * (svc: null) — the routing signal is the path itself. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const APP = "uicapp";
const PLAN = "uic-plan";
const QS = "?api-version=2023-12-01";
const base = (...tail) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Web/${tail.join("/")}${QS}`;
const put = (wire, path, body) => wire("PUT", path, { svc: null, headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

export default {
  "az-appservice": async (wire) => {
    await put(wire, base("serverfarms", PLAN), { location: "eastus", sku: { name: "B1" }, properties: { reserved: true } }).catch(() => {});
    await put(wire, base("sites", APP), {
      location: "eastus", kind: "app,linux",
      properties: { serverFarmId: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Web/serverfarms/${PLAN}`, siteConfig: { linuxFxVersion: "PYTHON|3.12" } },
    }).catch(() => {});
    return APP;
  },
  "site": async (wire, uniq) => {
    await put(wire, base("sites", uniq), { location: "eastus", kind: "app,linux" });
    return uniq;
  },
  "healthcheck": async (wire, uniq) => {
    await put(wire, base("sites", APP, "config", "web"), { properties: { healthCheckPath: `/${uniq}` } });
    return uniq;
  },
  "slot": async (wire, uniq) => {
    await put(wire, base("sites", APP, "slots", uniq), {});
    return uniq;
  },
  "customdomain": async (wire, uniq) => {
    const host = `${uniq}.example.com`;
    await put(wire, base("sites", APP, "hostNameBindings", host), {});
    return host;
  },
  "lock": async (wire, uniq) => {
    await put(wire, base("sites", APP, "providers", "Microsoft.Authorization", "locks", uniq), { properties: { level: "CanNotDelete" } });
    return uniq;
  },
};
