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
export const byId = (id) => CAT.models.find((m) => m.id === id);
/** Static fallback label (no live state): only the local small model is available without the Mesh. */
export const fallbackAvail = (id) => (id === CAT.local_id ? { state: "available", label: "Available", available: true } : { state: "needs_mesh", label: CAT.needs_mesh, available: false });
export const availText = (a, id) => (a || fallbackAvail(id)).label;
