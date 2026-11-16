/* Infer + Tune routes (lane bedrockui-b). Nav entries are in nav.js (lane bedrockui-a). */
import InferenceProfiles from "./InferenceProfiles.jsx";
import BatchInference from "./BatchInference.jsx";
import ProvisionedThroughput from "./ProvisionedThroughput.jsx";
import CustomModels from "./CustomModels.jsx";
import PromptRouters from "./PromptRouters.jsx";
import ImportedModels, { ImportJobDetail, ImportedModelDetail } from "./ImportedModels.jsx";
import TrainingJob from "./TrainingJob.jsx";
import MarketplaceDeployments from "./MarketplaceDeployments.jsx";

const page = (path, text, component) => ({ pattern: `/bedrock/${path}`, component, crumbs: () => [{ text, href: `#/bedrock/${path}` }] });

export const INFER_TUNE_ROUTES = [
  page("inference-profiles", "Inference profiles", InferenceProfiles),
  page("batch-inference", "Batch inference", BatchInference),
  page("provisioned-throughput", "Provisioned Throughput", ProvisionedThroughput),
  page("custom-models", "Custom models", CustomModels),
  { pattern: "/bedrock/custom-models/jobs/:id", component: TrainingJob, crumbs: (p) => [{ text: "Custom models", href: "#/bedrock/custom-models" }, { text: decodeURIComponent(p.id), href: `#/bedrock/custom-models/jobs/${p.id}` }] },
  page("imported-models", "Imported models", ImportedModels),
  { pattern: "/bedrock/imported-models/jobs/:id", component: ImportJobDetail, crumbs: (p) => [{ text: "Imported models", href: "#/bedrock/imported-models" }, { text: decodeURIComponent(p.id), href: `#/bedrock/imported-models/jobs/${p.id}` }] },
  { pattern: "/bedrock/imported-models/:id", component: ImportedModelDetail, crumbs: (p) => [{ text: "Imported models", href: "#/bedrock/imported-models" }, { text: decodeURIComponent(p.id), href: `#/bedrock/imported-models/${p.id}` }] },
  page("prompt-routers", "Prompt Routers", PromptRouters),
  page("marketplace-deployments", "Marketplace deployments", MarketplaceDeployments),
];
