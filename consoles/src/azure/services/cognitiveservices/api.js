/* Azure AI services / Cognitive Services over the native ARM wire:
 *   Control plane: ARM /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices/accounts/{name}
 *   Sub-resources: .../accounts/{name}/{deployments,commitmentPlans,raiPolicies}/{name}, listKeys, regenerateKey, usages, models
 *   Subscription scope: skus, checkDomainAvailability, deletedAccounts (soft-delete)
 * Served by core/azure_cognitiveservices_core.py through core/azure_arm_core.py — the same
 * azure-mgmt-cognitiveservices / armcognitiveservices SDK shapes work unchanged. */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.CognitiveServices", "accounts", "2024-10-01");
export const API_VERSION = ARM.apiVersion;

// kind -> allowed sku names (mirrors core/azure_cognitiveservices_core.py KINDS)
export const KINDS = {
  OpenAI: ["S0"],
  "AIServices": ["S0"],
  CognitiveServices: ["S0"],
  TextAnalytics: ["F0", "S", "S0", "S1", "S2", "S3", "S4"],
  ComputerVision: ["F0", "S1"],
  "CustomVision.Training": ["F0", "S0"],
  "CustomVision.Prediction": ["F0", "S0"],
  Face: ["F0", "S0"],
  FormRecognizer: ["F0", "S0"],
  ContentSafety: ["F0", "S0"],
  SpeechServices: ["F0", "S0"],
  TextTranslation: ["F0", "S1", "S2", "S3", "S4"],
  LUIS: ["F0", "S0"],
  "QnAMaker.v2": ["F0", "S0"],
  ImmersiveReader: ["S0"],
  Personalizer: ["F0", "S0"],
  AnomalyDetector: ["F0", "S0"],
  HealthInsights: ["F0", "S0"],
  ContentModerator: ["F0", "S0"],
};
/** Marketplace "Type" picker (create wizard) -> ARM kind. */
export const TYPE_TO_KIND = {
  "Azure OpenAI": "OpenAI",
  "Azure AI services multi-service account": "AIServices",
  "Computer Vision": "ComputerVision",
  "Content Safety": "ContentSafety",
  "Custom Vision (Training)": "CustomVision.Training",
  "Custom Vision (Prediction)": "CustomVision.Prediction",
  Face: "Face",
  "Document Intelligence": "FormRecognizer",
  "Speech services": "SpeechServices",
  Translator: "TextTranslation",
  Language: "TextAnalytics",
  "Anomaly Detector": "AnomalyDetector",
  Personalizer: "Personalizer",
  "Immersive Reader": "ImmersiveReader",
  "Health Insights": "HealthInsights",
  "Content Moderator": "ContentModerator",
};
export const KIND_LABEL = Object.fromEntries(Object.entries(TYPE_TO_KIND).map(([label, kind]) => [kind, label]));
export const MODEL_KINDS = ["OpenAI", "AIServices"];
export const NEEDS_SUBDOMAIN = new Set(["OpenAI", "AIServices", "ContentSafety", "FormRecognizer", "ComputerVision", "Face", "TextAnalytics", "HealthInsights", "ImmersiveReader"]);
export const DEPLOY_SKUS = ["Standard", "GlobalStandard", "ProvisionedManaged", "GlobalProvisionedManaged", "DataZoneStandard", "GlobalBatch", "DeveloperTier"];
// (format, name, version, maxCapacity) — mirrors core MODELS
export const MODELS = [
  ["OpenAI", "gpt-4o", "2024-05-13", 450], ["OpenAI", "gpt-4o", "2024-08-06", 450], ["OpenAI", "gpt-4o", "2024-11-20", 450],
  ["OpenAI", "gpt-4o-mini", "2024-07-18", 1000], ["OpenAI", "gpt-4", "turbo-2024-04-09", 80], ["OpenAI", "gpt-35-turbo", "0125", 1000],
  ["OpenAI", "o1", "2024-12-17", 100], ["OpenAI", "o3-mini", "2025-01-31", 1000],
  ["OpenAI", "text-embedding-ada-002", "2", 1000], ["OpenAI", "text-embedding-3-small", "1", 1000], ["OpenAI", "text-embedding-3-large", "1", 1000],
  ["OpenAI", "dall-e-3", "3.0", 2], ["OpenAI", "whisper", "001", 3], ["OpenAI", "tts", "001", 3],
];

const shape = (v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup });

export const listAccounts = async () => (await ARM.list()).map(shape);
export const getAccount = async (rg, name) => shape(await ARM.get(rg, name));
export const createAccount = (rg, name, body) => ARM.put(rg, name, body);
export const updateAccount = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteAccount = (rg, name) => ARM.remove(rg, name);

export const listKeys = (rg, name) => ARM.action(rg, name, "listKeys");
export const regenerateKey = (rg, name, keyName) => ARM.action(rg, name, "regenerateKey", { keyName });

// ── Model deployments (OpenAI / AIServices kinds only) ──────────────────────────────────
const deploymentsPath = (rg, name) => `${ARM.path(rg, name)}/deployments`;
export const listDeployments = async (rg, name) => (await restJson("GET", deploymentsPath(rg, name), { query: { "api-version": API_VERSION } })).value || [];
export const putDeployment = (rg, name, depName, body) =>
  restJson("PUT", `${deploymentsPath(rg, name)}/${encodeURIComponent(depName)}`, { query: { "api-version": API_VERSION }, body });
export const deleteDeployment = (rg, name, depName) =>
  restJson("DELETE", `${deploymentsPath(rg, name)}/${encodeURIComponent(depName)}`, { query: { "api-version": API_VERSION } });

// ── Quotas / usages ──────────────────────────────────────────────────────────────────────
export const listUsages = async (rg, name) => (await restJson("GET", `${ARM.path(rg, name)}/usages`, { query: { "api-version": API_VERSION } })).value || [];

// ── Locks (Microsoft.Authorization/locks, resource-scoped) ──────────────────────────────
const LOCK_API_VERSION = "2020-05-01";
const lockPath = (rg, name, lockName) => `${ARM.path(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;
export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to this account) ──
export const listActivityLog = async (rg, name, sinceIso) => {
  const rid = ARM.path(rg, name);
  const filter = sinceIso ? `resourceUri eq '${rid}' and eventTimestamp ge '${sinceIso}'` : `resourceUri eq '${rid}'`;
  const query = { "api-version": "2015-04-01", "$filter": filter };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Deleted accounts (soft-delete / restore / purge) ─────────────────────────────────────
const deletedPath = (loc, rg, name) => `/subscriptions/${getSubscription()}/providers/Microsoft.CognitiveServices/locations/${loc}/resourceGroups/${rg}/deletedAccounts${name ? `/${encodeURIComponent(name)}` : ""}`;
export const listDeletedAccounts = async () => (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.CognitiveServices/deletedAccounts`, { query: { "api-version": API_VERSION } })).value || [];
export const purgeDeletedAccount = (loc, rg, name) => restJson("DELETE", deletedPath(loc, rg, name), { query: { "api-version": API_VERSION } });
export const restoreAccount = (rg, name, loc, kind, sku) => ARM.put(rg, name, { location: loc, kind, sku: { name: sku }, properties: { restore: true } });

/** deletedAccounts id (.../locations/{loc}/resourceGroups/{rg}/deletedAccounts/{name}) -> {location, resourceGroup}. */
export const parseDeletedId = (id = "") => {
  const m = id.match(/\/locations\/([^/]+)\/resourceGroups\/([^/]+)\/deletedAccounts\//i);
  return { location: m?.[1] || "", resourceGroup: m?.[2] || "" };
};

export const endpoint = (kind, loc, sd) => (sd ? `https://${sd}.${kind === "OpenAI" ? "openai.azure.com" : "cognitiveservices.azure.com"}/` : `https://${loc}.api.cognitive.microsoft.com/`);

// ── create-account form model -> ARM body ────────────────────────────────────────────────
export function toArmBody(f) {
  return {
    location: f.location,
    kind: f.kind,
    sku: { name: f.pricingTier },
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    identity: f.identity ? { type: "SystemAssigned" } : undefined,
    properties: {
      ...(f.customSubDomainName ? { customSubDomainName: f.customSubDomainName } : {}),
      publicNetworkAccess: f.networkAccess === "disabled" ? "Disabled" : "Enabled",
      networkAcls: { defaultAction: f.networkAccess === "selected" ? "Deny" : "Allow" },
    },
  };
}
