/* Managed Kubernetes (AKS / GKE / EKS) tier gate for the v4 consoles.
 *
 * Policy (core/tier_policy.py category "kubernetes", enforced server-side by core/k8s_tier_gate.py):
 * Pro / Max / Enterprise only; Pro gets its primary cloud only; Free and nano / micro / lite are locked.
 * The UI never decides on its own what the server will allow: it reads GET <base>/api/runtime/tier, whose
 * `kubernetes_locked.<cloud>` verdict comes from the same gate (offline appliance and the Nano service worker
 * both serve it).  If the endpoint is unreachable or does not say, the console FAILS CLOSED (locked) -
 * the server / Nano gate would refuse the calls anyway.
 *
 * Theme-agnostic on purpose (plain DOM + CSS system colors) so the same pane serves the Fluent (Azure),
 * MUI (GCP) and Cloudscape (AWS) lenses.
 */
import { useEffect, useState } from "react";
import { WIRE_BASE } from "./wire.js";

const CLOUD_LABEL = { azure: "Azure Kubernetes Service (AKS)", gcp: "Google Kubernetes Engine (GKE)", aws: "Amazon EKS" };
const UNLOCKED = ["pro", "max", "enterprise"];
export const UPGRADE_URL = "https://vyomi.cloud/pricing";

let cached = null;
function loadTier() {
  if (!cached) {
    const base = WIRE_BASE.replace(/\/_wire$/, "");
    cached = fetch(`${base}/api/runtime/tier`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  }
  return cached;
}
export const refreshTier = () => { cached = null; return loadTier(); };

/** Resolve the lock verdict for one cloud from the tier payload (server verdict first, client derivation as fallback). */
export function verdictFor(cloud, t) {
  const tier = String(t?.active_tier || "free").toLowerCase();
  const sv = t?.kubernetes_locked?.[cloud];
  if (sv && typeof sv.locked === "boolean") return { locked: sv.locked, tier, reason: sv.reason, required: sv.required_tiers || ["pro", "max", "enterprise"] };
  if (!t) return { locked: true, tier: "unknown", reason: "The plan could not be determined, so managed Kubernetes stays locked.", required: ["pro", "max", "enterprise"] };
  if (!UNLOCKED.includes(tier)) return { locked: true, tier, required: ["pro", "max", "enterprise"] };
  if (tier === "pro" && t.primary_cloud !== cloud) return { locked: true, tier, required: ["max", "enterprise"], proPrimary: t.primary_cloud || "" };
  return { locked: false, tier };
}

/** { ready, locked, tier, ... } for a cloud's managed Kubernetes. `locked` is true until the plan is known. */
export function useK8sLock(cloud) {
  const [v, setV] = useState({ ready: false, locked: true, tier: "" });
  useEffect(() => {
    let live = true;
    loadTier().then((t) => { if (live) setV({ ready: true, ...verdictFor(cloud, t) }); });
    return () => { live = false; };
  }, [cloud]);
  return v;
}

export function LockIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" style={{ verticalAlign: "-2px" }}>
      <path d="M17 8h-1V6a4 4 0 0 0-8 0v2H7a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-9a2 2 0 0 0-2-2zm-7-2a2 2 0 0 1 4 0v2h-4V6z" />
    </svg>
  );
}

/** Small "Pro" lock pill for service lists. */
export function LockBadge({ label = "Pro+" }) {
  return (
    <span title="Managed Kubernetes requires the Pro, Max or Enterprise plan" data-testid="k8s-lock-badge"
      style={{ marginLeft: 8, padding: "1px 6px", fontSize: 11, borderRadius: 10, border: "1px solid currentColor", opacity: 0.75, whiteSpace: "nowrap" }}>
      <LockIcon size={10} /> {label}
    </span>
  );
}

/** Read-only locked pane that replaces the service's page (no create, no kubectl terminal, no backup tab). */
export function K8sLocked({ cloud, v }) {
  const name = CLOUD_LABEL[cloud] || "Managed Kubernetes";
  const proOnly = v?.tier === "pro";
  const plans = proOnly ? "Max or Enterprise" : "Pro (one primary cloud), Max or Enterprise";
  return (
    <div className="vy-page" data-testid="k8s-locked" role="region" aria-label={`${name} is locked`}
      style={{ maxWidth: 760, margin: "32px auto", padding: "0 16px", font: "inherit", color: "inherit" }}>
      <h1 style={{ fontSize: 24, fontWeight: 600, margin: "0 0 8px" }}><LockIcon size={22} /> {name}</h1>
      <p style={{ fontSize: 15, margin: "0 0 16px" }}>
        {proOnly
          ? <>Your <b>Pro</b> plan includes managed Kubernetes on your primary cloud{v?.proPrimary ? <> (<b>{v.proPrimary}</b>)</> : null} only.</>
          : <>Managed Kubernetes is not included in your <b>{v?.tier ? v.tier.charAt(0).toUpperCase() + v.tier.slice(1) : "current"}</b> plan.</>}
        {" "}It is available on <b>{plans}</b>.
      </p>
      <div style={{ border: "1px solid rgba(128,128,128,.45)", borderRadius: 8, padding: 16, marginBottom: 16, background: "rgba(128,128,128,.08)" }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Read-only while locked</div>
        <ul style={{ margin: 0, paddingLeft: 20, lineHeight: 1.7 }}>
          <li>Clusters, node pools, workloads and backups are not available</li>
          <li>Create actions, the kubectl / Run command terminal and Backup are disabled</li>
          <li>Calls from the CLI or an SDK are refused with a {cloud === "azure" ? "FeatureNotAvailableForTier" : cloud === "gcp" ? "PERMISSION_DENIED" : "AccessDeniedException"} error</li>
        </ul>
      </div>
      <a href={UPGRADE_URL} target="_blank" rel="noopener noreferrer" data-testid="k8s-upgrade-cta"
        style={{ display: "inline-block", padding: "9px 18px", borderRadius: 6, background: "#0b6bcb", color: "#fff", textDecoration: "none", fontWeight: 600 }}>
        Upgrade to {proOnly ? "Max" : "Pro or Max"}
      </a>
    </div>
  );
}
