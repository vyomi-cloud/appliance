/* Infer + Tune routes (lane bedrockui-b). Nav entries are in nav.js (lane bedrockui-a). */
import InferenceProfiles from "./InferenceProfiles.jsx";
import BatchInference from "./BatchInference.jsx";
import ProvisionedThroughput from "./ProvisionedThroughput.jsx";
import CustomModels from "./CustomModels.jsx";
import PromptRouters from "./PromptRouters.jsx";
import MarketplaceDeployments from "./MarketplaceDeployments.jsx";

const page = (path, text, component) => ({ pattern: `/bedrock/${path}`, component, crumbs: () => [{ text, href: `#/bedrock/${path}` }] });

export const INFER_TUNE_ROUTES = [
  page("inference-profiles", "Inference profiles", InferenceProfiles),
  page("batch-inference", "Batch inference", BatchInference),
  page("provisioned-throughput", "Provisioned Throughput", ProvisionedThroughput),
  page("custom-models", "Custom models", CustomModels),
  page("prompt-routers", "Prompt Routers", PromptRouters),
  page("marketplace-deployments", "Marketplace deployments", MarketplaceDeployments),
];
