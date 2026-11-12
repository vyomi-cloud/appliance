/* Function Apps over the native Azure wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Web/sites/{name}
 *   Sub-resources: functions, config/appsettings, config/connectionstrings, host/default/*,
 *                  locks — all native ARM calls on the same resource, routed to
 *                  core/azure_webapp_core.py by the shared ARM core (core/azure_arm_core.py /
 *                  providers/azure_services.py), exactly like Storage and Container Apps. */
import { armType, getSubscription, parseId } from "../../kit/arm.js";
import { restJson } from "../../../common/wire.js";

export const ARM = armType("Microsoft.Web", "sites", "2023-12-01");
const WORKSPACES = armType("Microsoft.OperationalInsights", "workspaces", "2022-10-01");
const METRIC_ALERTS = armType("Microsoft.Insights", "metricAlerts", "2018-03-01");

const shape = (s) => ({ ...s, resourceGroup: parseId(s.id).resourceGroup });

// Microsoft.Web/sites lists BOTH kinds, like real ARM; this blade shows kind=functionapp only.
export const listFunctionApps = async () => (await ARM.list()).filter((s) => /functionapp/i.test(s.kind || "")).map(shape);
export const getFunctionApp = async (rg, name) => shape(await ARM.get(rg, name));
export const createFunctionApp = (rg, name, body) => ARM.put(rg, name, body);
export const updateFunctionApp = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteFunctionApp = (rg, name) => ARM.remove(rg, name);
export const startFunctionApp = (rg, name) => ARM.action(rg, name, "start");
export const stopFunctionApp = (rg, name) => ARM.action(rg, name, "stop");
export const restartFunctionApp = (rg, name) => ARM.action(rg, name, "restart");
export const publishProfile = async (rg, name, reset = false) => (await ARM.action(rg, name, reset ? "resetpublishxml" : "publishxml")).value;

// armType has no notion of a nested sub-path PUT; build it directly.
const putSub = (rg, name, sub, body) => restJson("PUT", `${ARM.path(rg, name)}/${sub}`, { query: { "api-version": ARM.apiVersion }, body });

// ── app settings / connection strings (Environment variables) ───────────────────────────
export const listAppSettings = async (rg, name) => (await ARM.action(rg, name, "config/appsettings")).properties || {};
export const setAppSettings = async (rg, name, props) => (await putSub(rg, name, "config/appsettings", { properties: props })).properties || {};
export const listConnectionStrings = async (rg, name) => (await ARM.action(rg, name, "config/connectionstrings")).properties || {};
export const setConnectionStrings = async (rg, name, props) => (await putSub(rg, name, "config/connectionstrings", { properties: props })).properties || {};

// ── host keys (App keys) ─────────────────────────────────────────────────────────────────
export const listHostKeys = (rg, name) => ARM.action(rg, name, "host/default/listKeys");
export const putHostKey = (rg, name, bucket, keyName, value) =>
  restJson("PUT", `${ARM.path(rg, name)}/host/default/${bucket}/${encodeURIComponent(keyName)}`, { query: { "api-version": ARM.apiVersion }, body: { properties: { value } } });
export const deleteHostKey = (rg, name, bucket, keyName) =>
  restJson("DELETE", `${ARM.path(rg, name)}/host/default/${bucket}/${encodeURIComponent(keyName)}`, { query: { "api-version": ARM.apiVersion } });

// ── activity log (Microsoft.Insights/eventtypes/management/values, filtered to this site) ──
export const listActivityLog = async (rg, name) => {
  const rid = ARM.path(rg, name);
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${rid}'` };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── locks ─────────────────────────────────────────────────────────────────────────────────
export const listLocks = async (rg, name) => (await restJson("GET", `${ARM.path(rg, name)}/locks`, { query: { "api-version": ARM.apiVersion } })).value || [];
export const putLock = (rg, name, lockName, level, notes) =>
  restJson("PUT", `${ARM.path(rg, name)}/locks/${encodeURIComponent(lockName)}`, { query: { "api-version": ARM.apiVersion }, body: { properties: { level, notes } } });
export const deleteLock = (rg, name, lockName) =>
  restJson("DELETE", `${ARM.path(rg, name)}/locks/${encodeURIComponent(lockName)}`, { query: { "api-version": ARM.apiVersion } });

// ── identity (top-level sibling of `properties`, like real ARM) ─────────────────────────
export const updateIdentity = (rg, name, identity) => ARM.patch(rg, name, { identity });

// ── General settings sub-fields of config/web (siteConfig) — CORS, health check path, … ──
export const getSiteConfig = async (rg, name) => (await ARM.action(rg, name, "config/web")).properties || {};
export const updateSiteConfig = async (rg, name, props) => (await putSub(rg, name, "config/web", { properties: props })).properties || {};

// ── custom domains (hostNameBindings) + the SNI/IP SSL binding a "Certificates" view reads ──
const domainsPath = (rg, name) => `${ARM.path(rg, name)}/hostNameBindings`;
export const listCustomDomains = async (rg, name) => (await restJson("GET", domainsPath(rg, name), { query: { "api-version": ARM.apiVersion } })).value || [];
export const addCustomDomain = (rg, name, host, sslState = "Disabled") =>
  restJson("PUT", `${domainsPath(rg, name)}/${encodeURIComponent(host)}`, { query: { "api-version": ARM.apiVersion }, body: { properties: { sslState } } });
export const removeCustomDomain = (rg, name, host) => restJson("DELETE", `${domainsPath(rg, name)}/${encodeURIComponent(host)}`, { query: { "api-version": ARM.apiVersion } });

// ── diagnostic settings (Microsoft.Insights/diagnosticSettings, a real ARM extension resource
// scoped to this site's own id — core/azure_monitor_core.py; same engine every Azure resource's
// "Diagnostic settings" page uses) ───────────────────────────────────────────────────────
const DIAG_API_VERSION = "2021-05-01-preview";
const diagPath = (rg, name) => `${ARM.path(rg, name)}/providers/Microsoft.Insights/diagnosticSettings`;
export const listDiagnosticSettings = async (rg, name) =>
  (await restJson("GET", diagPath(rg, name), { query: { "api-version": DIAG_API_VERSION } })).value || [];
export const putDiagnosticSetting = (rg, name, dsName, body) =>
  restJson("PUT", `${diagPath(rg, name)}/${encodeURIComponent(dsName)}`, { query: { "api-version": DIAG_API_VERSION }, body });
export const deleteDiagnosticSetting = (rg, name, dsName) =>
  restJson("DELETE", `${diagPath(rg, name)}/${encodeURIComponent(dsName)}`, { query: { "api-version": DIAG_API_VERSION } });
export const listWorkspaces = async () => (await WORKSPACES.list()).map((w) => ({ ...w, resourceGroup: parseId(w.id).resourceGroup }));

// ── authentication (Easy Auth) — require-auth toggle, enforced on invoke ─────────────────
export const getAuthSettings = async (rg, name) => (await ARM.action(rg, name, "config/authsettingsv2")).properties || {};
export const updateAuthSettings = async (rg, name, enabled) => (await putSub(rg, name, "config/authsettingsv2", { properties: { platform: { enabled } } })).properties || {};

// ── invocation telemetry (Metrics, Logs, Log stream, Events, Advisor, App Insights panels —
// all read the SAME real ring buffer the invoke sandbox appends to) ──────────────────────
export const listInvocationLogs = async (rg, name) => (await restJson("GET", `${ARM.path(rg, name)}/invocationlogs`, { query: { "api-version": ARM.apiVersion } })).value || [];
export const runHealthCheck = (rg, name) => restJson("GET", `${ARM.path(rg, name)}/healthcheck`, { query: { "api-version": ARM.apiVersion } });
export const listAdvisorRecommendations = async (rg, name) => (await restJson("GET", `${ARM.path(rg, name)}/advisorrecommendations`, { query: { "api-version": ARM.apiVersion } })).value || [];
export const listDiagnoseDetectors = async (rg, name) => (await restJson("GET", `${ARM.path(rg, name)}/diagnosedetectors`, { query: { "api-version": ARM.apiVersion } })).value || [];

// ── alerts (Microsoft.Insights/metricAlerts, subscription-wide generic CRUD — core/azure_monitor_core.py
// — scoped to this app via `properties.scopes`, the real shape of a resource's Alerts blade) ──
export const listMetricAlertsFor = async (rg, name) => {
  const site = ARM.path(rg, name).toLowerCase();
  return (await METRIC_ALERTS.list()).filter((a) => (a.properties?.scopes || []).some((s) => s.toLowerCase() === site));
};
export const putMetricAlert = (rg, alertName, body) => METRIC_ALERTS.put(rg, alertName, body);
export const deleteMetricAlert = (rg, alertName) => METRIC_ALERTS.remove(rg, alertName);

// ── functions ─────────────────────────────────────────────────────────────────────────────
const fnPath = (rg, name, fn) => `${ARM.path(rg, name)}/functions${fn ? "/" + encodeURIComponent(fn) : ""}`;
export const listFunctions = async (rg, name) => (await restJson("GET", fnPath(rg, name), { query: { "api-version": ARM.apiVersion } })).value || [];
export const getFunction = (rg, name, fn) => restJson("GET", fnPath(rg, name, fn), { query: { "api-version": ARM.apiVersion } });
export const createFunction = (rg, name, fn, body) => restJson("PUT", fnPath(rg, name, fn), { query: { "api-version": ARM.apiVersion }, body });
export const deleteFunction = (rg, name, fn) => restJson("DELETE", fnPath(rg, name, fn), { query: { "api-version": ARM.apiVersion } });
export const listFunctionKeys = (rg, name, fn) => restJson("POST", `${fnPath(rg, name, fn)}/listKeys`, { query: { "api-version": ARM.apiVersion }, body: {} });
export const invokeFunction = (rg, name, fn, req) => restJson("POST", `${fnPath(rg, name, fn)}/invoke`, { query: { "api-version": ARM.apiVersion }, body: req });

// ── create-form model → ARM body ────────────────────────────────────────────────────────
export const RUNTIMES = {
  "Python": ["3.12", "3.11", "3.10", "3.9"], ".NET": ["8.0", "6.0"], "Node.js": ["20 LTS", "18 LTS"],
  "Java": ["21", "17", "11"], "PowerShell Core": ["7.4", "7.2"], "Custom Handler": ["-"],
};

export function toArmBody(f) {
  return {
    location: f.location, kind: "functionapp",
    properties: {
      reserved: true, httpsOnly: true,
      siteConfig: { _runtime: f.runtime, _version: f.version, appSettings: f.openai ? [{ name: "AZURE_OPENAI_ENABLED", value: "true" }] : [] },
      functionAppConfig: {
        runtime: { name: f.runtime.toLowerCase().replace(".net", "dotnet-isolated").replace(" core", "").replace(".js", ""), version: f.version },
        scaleAndConcurrency: { instanceMemoryMB: 2048, maximumInstanceCount: 100, alwaysReady: [], triggers: { http: { perInstanceConcurrency: 16 } } },
        deployment: { storage: { type: "blobContainer", value: `https://${f.storageAccount || "vyomistorage"}.blob.core.windows.net/app-package` } },
      },
      publicNetworkAccess: f.publicAccess === false ? "Disabled" : "Enabled",
      vnetRouteAllEnabled: !!f.vnetIntegration,
    },
    tags: Object.fromEntries((f.tags || []).filter((t) => t.name).map((t) => [t.name, t.value])),
  };
}

export const TEMPLATES = [
  ["httptrigger", "HTTP trigger", [{ authLevel: "function", type: "httpTrigger", direction: "in", name: "req", methods: ["get", "post"] }, { type: "http", direction: "out", name: "$return" }]],
  ["timertrigger", "Timer trigger", [{ type: "timerTrigger", direction: "in", name: "myTimer", schedule: "0 */5 * * * *" }]],
  ["blobtrigger", "Azure Blob Storage trigger", [{ type: "blobTrigger", direction: "in", name: "myBlob", path: "samples-workitems/{name}", connection: "AzureWebJobsStorage" }]],
  ["queuetrigger", "Azure Queue Storage trigger", [{ type: "queueTrigger", direction: "in", name: "myQueueItem", queueName: "myqueue-items", connection: "AzureWebJobsStorage" }]],
];

export function functionBody(templateKey, authLevel) {
  const t = TEMPLATES.find((x) => x[0] === templateKey) || TEMPLATES[0];
  const bindings = t[2].map((b) => (b.type === "httpTrigger" ? { ...b, authLevel: authLevel || "function" } : b));
  return { properties: { config: { bindings }, entryPoint: "main", files: { "__init__.py": DEFAULT_CODE } } };
}

export const DEFAULT_CODE = 'def main(req):\n    """HTTP trigger entry point — echoes the request back."""\n    return {"echo": req, "message": "hello from Azure Functions"}\n';
