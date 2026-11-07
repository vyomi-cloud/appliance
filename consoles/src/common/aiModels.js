/* The ten booster-mesh models every AI console shows (generated catalogue: core/ai_model_catalog.py -> ai-model-catalog.json).
 * Availability is live from each cloud's own list API (vyomiAvailability); with no booster only the local small model is available. */
import CAT from "./ai-model-catalog.json";

export const AI_MODELS = CAT.models;
export const AI_CHAT = CAT.models.filter((m) => m.kind === "chat");
export const AI_EMBED = CAT.models.filter((m) => m.kind === "embed");
export const DEFAULT_CHAT = CAT.default_chat;
export const DEFAULT_EMBED = CAT.default_embed;
export const NEEDS_BOOSTER = CAT.needs_booster;
export const byId = (id) => CAT.models.find((m) => m.id === id);
/** Static fallback label (no live state): only the local small model is available without a booster. */
export const fallbackAvail = (id) => (id === CAT.local_id ? { state: "available", label: "Available", available: true } : { state: "needs_booster", label: CAT.needs_booster, available: false });
export const availText = (a, id) => (a || fallbackAvail(id)).label;
