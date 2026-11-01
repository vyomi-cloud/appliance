/* UI-conformance fixtures for Azure Container Apps — native ARM wire setup run by
 * consoles/tests/ui-conformance.mjs. Each returns the text the page must then show
 * (liveness: proves the page is not static). ARM requests carry no AWS signature
 * (svc: null) — the routing signal is the path itself. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const ENV = "uiccae";
const APP = "uicapp";
const JOB = "uicjob";
const QS = "?api-version=2024-03-01";
const LOCKQS = "?api-version=2020-05-01";
const base = (...tail) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.App/${tail.join("/")}${QS}`;
const put = (wire, path, body) => wire("PUT", path, { svc: null, headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const patch = (wire, path, body) => wire("PATCH", path, { svc: null, headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

const envId = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.App/managedEnvironments/${ENV}`;

const appBody = (extraSecret) => ({
  location: "eastus",
  properties: {
    managedEnvironmentId: envId,
    configuration: {
      ingress: { external: true, targetPort: 80 },
      secrets: [{ name: "apikey", value: "secret" }, ...(extraSecret ? [{ name: extraSecret, value: "x" }] : [])],
    },
    template: { containers: [{ name: "web", image: "nginx", env: [{ name: "PORT", value: "80" }], resources: { cpu: 0.5, memory: "1Gi" } }] },
  },
});

export default {
  "az-cae": async (wire) => {
    await put(wire, base("managedEnvironments", ENV), { location: "eastus" }).catch(() => {});
    await put(wire, base("containerApps", APP), appBody()).catch(() => {});
    await put(wire, base("jobs", JOB), {
      location: "eastus",
      properties: { environmentId: envId, configuration: { triggerType: "Manual" }, template: { containers: [{ image: "busybox" }] } },
    }).catch(() => {});
    return APP;
  },
  "live-env": async (wire, uniq) => { await put(wire, base("managedEnvironments", uniq), { location: "eastus" }); return uniq; },
  "live-app": async (wire, uniq) => { await put(wire, base("containerApps", uniq), { location: "eastus", properties: { template: { containers: [{ image: "nginx" }] } } }); return uniq; },
  "live-job": async (wire, uniq) => {
    await put(wire, base("jobs", uniq), { location: "eastus", properties: { configuration: { triggerType: "Manual" }, template: { containers: [{ image: "busybox" }] } } });
    return uniq;
  },
  "live-tag-env": async (wire, uniq) => { await patch(wire, base("managedEnvironments", ENV), { tags: { [uniq]: "1" } }); return uniq; },
  "live-tag-app": async (wire, uniq) => { await patch(wire, base("containerApps", APP), { tags: { [uniq]: "1" } }); return uniq; },
  "live-tag-job": async (wire, uniq) => { await patch(wire, base("jobs", JOB), { tags: { [uniq]: "1" } }); return uniq; },
  "live-secret": async (wire, uniq) => { await put(wire, base("containerApps", APP), appBody(uniq)); return uniq; },
  "live-dapr": async (wire, uniq) => { await put(wire, base("managedEnvironments", ENV, "daprComponents", uniq), { properties: { componentType: "state.redis" } }); return uniq; },
  "live-cert": async (wire, uniq) => { await put(wire, base("managedEnvironments", ENV, "certificates", uniq), { properties: {} }); return uniq; },
  "live-lock-env": async (wire, uniq) => {
    await wire("PUT", `${base("managedEnvironments", ENV).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}${LOCKQS}`,
      { svc: null, headers: { "content-type": "application/json" }, body: JSON.stringify({ properties: { level: "CanNotDelete" } }) });
    return uniq;
  },
  "live-lock-app": async (wire, uniq) => {
    await wire("PUT", `${base("containerApps", APP).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}${LOCKQS}`,
      { svc: null, headers: { "content-type": "application/json" }, body: JSON.stringify({ properties: { level: "CanNotDelete" } }) });
    return uniq;
  },
  "live-lock-job": async (wire, uniq) => {
    await wire("PUT", `${base("jobs", JOB).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}${LOCKQS}`,
      { svc: null, headers: { "content-type": "application/json" }, body: JSON.stringify({ properties: { level: "CanNotDelete" } }) });
    return uniq;
  },
};
