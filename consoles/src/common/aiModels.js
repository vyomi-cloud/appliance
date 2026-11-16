/* The ten mesh-llm models every AI console shows (generated catalogue: core/ai_model_catalog.py -> ai-model-catalog.json).
 * Availability is live from each cloud's own list API (vyomiAvailability); with no Mesh only the local small model is available. */
import MESH from "./ai-model-catalog.json";
import WEB from "./ai-model-catalog-web.json";
/* Nano (browser) serves only the small WebLLM models; the offline appliance / Mesh serves the ten open-source models. */
const IS_NANO = typeof location !== "undefined" && /(^|\/)nano(\/|$)/.test(location.pathname);
const CAT = IS_NANO ? WEB : MESH;

export const AI_MODELS = CAT.models;
export const AI_CHAT = CAT.models.filter((m) => m.kind === "chat");
export const AI_EMBED = CAT.models.filter((m) => m.kind === "embed");
export const DEFAULT_CHAT = CAT.default_chat;
export const DEFAULT_EMBED = CAT.default_embed;
export const NEEDS_MESH = CAT.needs_mesh;
export const AI_SPECIAL = CAT.special || [];
export const byId = (id) => CAT.models.find((m) => m.id === id) || AI_SPECIAL.find((m) => m.id === id);
/** Role models (vision / reasoning, Mesh only) join the pickers ONLY once a cloud list API reports them served (vyomiAvailability.available).
 *  Arrays are mutated in place so every importer sees them; never present while no role server runs. */
export function markServed(availById) {
  for (const m of AI_SPECIAL) {
    const on = !!(availById && availById[m.id] && availById[m.id].available);
    for (const arr of [AI_MODELS, ...(m.kind === "embed" ? [AI_EMBED] : [AI_CHAT])]) {
      const i = arr.findIndex((x) => x.id === m.id);
      if (on && i < 0) arr.push(m); else if (!on && i >= 0) arr.splice(i, 1);
    }
  }
}
/** Static fallback label (no live state): only the local small model is available without the Mesh. */
export const fallbackAvail = (id) => (id === CAT.local_id ? { state: "available", label: "Available", available: true } : { state: "needs_mesh", label: CAT.needs_mesh, available: false });
export const availText = (a, id) => (a || fallbackAvail(id)).label;
