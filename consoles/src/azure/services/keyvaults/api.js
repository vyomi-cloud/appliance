/* Key vaults over the native Azure wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.KeyVault/vaults/{name}
 *   Data planes:   Key Vault Keys REST (/keys/...?api-version=7.4) and Key Vault Secrets REST
 *                  (/secrets/...?api-version=7.4) — the shape azure-keyvault-keys /
 *                  azure-keyvault-secrets use against a vault endpoint.
 * Vyomi's keys/secrets stores are global per Nano instance (core/aws_wire_router.py — one
 * InMemoryKeyStore / InMemoryKvStore shared by every vault), the same simplification the AWS
 * lens makes for KMS/Secrets Manager: not tied to a single resource ARN/vault either. */
import { restJson } from "../../../common/wire.js";
import { armType, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.KeyVault", "vaults", "2023-07-01");
export const KV_API_VERSION = "7.4";

const shape = (v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup });

export const listVaults = async () => (await ARM.list()).map(shape);
export const getVault = async (rg, name) => shape(await ARM.get(rg, name));
export const createVault = (rg, name, body) => ARM.put(rg, name, body);
export const updateVault = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteVault = (rg, name) => ARM.remove(rg, name);

export const vaultUri = (name) => `https://${name}.vault.azure.net/`;
export const skuLabel = (sku) => (sku?.name === "premium" ? "Premium" : "Standard");

// ── Keys data plane (Key Vault Keys REST) ───────────────────────────────────────────────
const kv = (method, path, { body } = {}) => restJson(method, path, { query: { "api-version": KV_API_VERSION }, body });

export const listKeys = async () => (await kv("GET", "/keys")).value || [];
export const createKey = (name, body) => kv("POST", `/keys/${encodeURIComponent(name)}/create`, { body });
export const getKey = (name, version) => kv("GET", `/keys/${encodeURIComponent(name)}${version ? `/${version}` : ""}`);
export const deleteKey = (name) => kv("DELETE", `/keys/${encodeURIComponent(name)}`);

/** kid (https://vault/keys/{name}/{version}) -> {name, version}. */
export const parseKid = (kid = "") => {
  const m = kid.match(/\/keys\/([^/]+)\/([^/]+)$/);
  return { name: m?.[1] || "", version: m?.[2] || "" };
};

// ── Secrets data plane (Key Vault Secrets REST) ─────────────────────────────────────────
export const listSecrets = async () => (await kv("GET", "/secrets")).value || [];
export const setSecret = (name, body) => kv("PUT", `/secrets/${encodeURIComponent(name)}`, { body });
export const getSecret = (name, version) => kv("GET", `/secrets/${encodeURIComponent(name)}${version ? `/${version}` : ""}`);
export const listSecretVersions = async (name) => (await kv("GET", `/secrets/${encodeURIComponent(name)}/versions`)).value || [];
export const deleteSecret = (name) => kv("DELETE", `/secrets/${encodeURIComponent(name)}`);

/** secret id (https://vault/secrets/{name}[/{version}]) -> {name, version}. */
export const parseSecretId = (id = "") => {
  const m = id.match(/\/secrets\/([^/]+)(?:\/([^/]+))?$/);
  return { name: m?.[1] || "", version: m?.[2] || "" };
};

// ── Certificates data plane (Key Vault Certificates REST) ──────────────────────────────
export const listCertificates = async () => (await kv("GET", "/certificates")).value || [];
export const createCertificate = (name, body) => kv("POST", `/certificates/${encodeURIComponent(name)}/create`, { body });
export const getCertificate = (name) => kv("GET", `/certificates/${encodeURIComponent(name)}`);
export const deleteCertificate = (name) => kv("DELETE", `/certificates/${encodeURIComponent(name)}`);

/** base64url (no padding) -> uppercase hex, the portal's thumbprint display for `x5t`. */
export const thumbprintHex = (x5t) => {
  const b64 = (x5t || "").replace(/-/g, "+").replace(/_/g, "/");
  return atob(b64).split("").map((c) => c.charCodeAt(0).toString(16).padStart(2, "0")).join("").toUpperCase();
};

/** certificate id (https://vault/certificates/{name}) -> {name}. */
export const parseCertId = (id = "") => {
  const m = id.match(/\/certificates\/([^/]+)$/);
  return { name: m?.[1] || "" };
};

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ──────────
const LOCK_API_VERSION = "2020-05-01";
const lockPath = (rg, name, lockName) => `${ARM.path(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;

export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── create-vault form model → ARM body ──────────────────────────────────────────────────
export function toArmBody(f) {
  return {
    location: f.location,
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      tenantId: "00000000-0000-0000-0000-000000000000",
      sku: { family: "A", name: f.pricingTier.toLowerCase() },
      accessPolicies: [],
      enableRbacAuthorization: f.permissionModel === "rbac",
      enabledForDeployment: f.vmDeployment,
      enabledForTemplateDeployment: f.armDeployment,
      enabledForDiskEncryption: f.diskEncryption,
      enableSoftDelete: true,
      softDeleteRetentionInDays: f.retentionDays,
      enablePurgeProtection: f.purgeProtection,
      publicNetworkAccess: f.networkAccess === "disabled" ? "Disabled" : "Enabled",
      networkAcls: { defaultAction: f.networkAccess === "selected" ? "Deny" : "Allow", bypass: "AzureServices" },
    },
  };
}
