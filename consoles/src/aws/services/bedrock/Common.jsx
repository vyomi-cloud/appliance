import StatusIndicator from "@cloudscape-design/components/status-indicator";

export const stat = (s) => (
  <StatusIndicator type={["READY", "ACTIVE", "PREPARED", "AVAILABLE", "COMPLETE", "ENABLED"].includes(s) ? "success" : ["FAILED", "DELETING"].includes(s) ? "error" : s === "NOT_PREPARED" ? "pending" : "in-progress"}>{s}</StatusIndicator>
);
import { DEFAULT_CHAT, DEFAULT_EMBED, availText } from "../../../common/aiModels.js";

// The ten booster-mesh models (core/ai_model_catalog.py); Bedrock lists them as vyomi.<id>.
export const NOVA = `vyomi.${DEFAULT_CHAT}`;
export const modelArn = (id) => `arn:aws:bedrock:us-east-1::foundation-model/${id}`;
export const TITAN = modelArn(`vyomi.${DEFAULT_EMBED}`);
/** Model picker option: provider-correct name, model id and the live availability (Needs Booster (Pro/Max) without a booster). */
export const modelOption = (m) => ({ label: m.modelName, description: m.modelId, value: m.modelId, tags: [m.providerName, availText(m.vyomiAvailability, String(m.modelId).replace(/^vyomi\./, ""))] });
