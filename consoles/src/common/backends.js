/* "How Vyomi runs this service" — data helpers shared by the AWS / GCP / Azure consoles.
 *
 * Narrative per service comes from core/capabilities/backends/<cloud>.json (schema:
 * docs/architecture/v4.0/BACKENDS-SCHEMA.md), bundled at build time through the
 * `vyomi-backends:<cloud>` virtual module (consoles/build.mjs) so it works offline and on
 * Nano with no fetch. Fidelity numbers are NOT in that file: they are derived here from the
 * capability registry each console kit already bundles (levels per substrate). */

export const KIND_LABEL = {
  opensource: "Open source",
  inhouse: "Built by Vyomi",
  hybrid: "Hybrid",
  unavailable: "Not available in the browser",
};

export const LEVELS = [
  ["full", "Full"],
  ["limited", "Dev Simplified"],
  ["config_only", "Config only"],
  ["not_simulated", "Not simulated"],
];

/** Narrative entry for a service id, or null when the data file has no entry (never invented). */
export function backendInfo(data, id) {
  const e = data && id && Object.prototype.hasOwnProperty.call(data, id) ? data[id] : null;
  return e && typeof e === "object" ? e : null;
}

/** Counts of features per level for one service on one substrate, from the registry file
 *  (`{ "<cloud>.<svc>.<feature>": { level: {offline, nano} } }`). Null when there is no registry. */
export function fidelity(registryFile, substrate) {
  if (!registryFile) return null;
  const counts = { full: 0, limited: 0, config_only: 0, not_simulated: 0 };
  let total = 0;
  for (const [k, f] of Object.entries(registryFile)) {
    if (k.startsWith("$") || !f || typeof f !== "object" || !f.level) continue;
    const lv = f.level[substrate] || f.level.offline || "not_simulated";
    counts[lv in counts ? lv : "not_simulated"]++;
    total++;
  }
  return total ? { counts, total } : null;
}
