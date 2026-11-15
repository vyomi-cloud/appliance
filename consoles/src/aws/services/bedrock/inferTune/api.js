/* Bedrock control plane for the Infer + Tune pages (real wire shapes, signing name `bedrock`; core/bedrock_ctl_core.py). */
import { awsRest } from "../../../../common/wire.js";
import { ACCOUNT, roleArn } from "../api.js";

const B = (m, p, o) => awsRest("bedrock", m, p, o);
const enc = encodeURIComponent;
export { ACCOUNT, roleArn };

// inference profiles
export const listProfiles = (type) => B("GET", "/inference-profiles", { query: { type, maxResults: "1000" } }).then((r) => r.inferenceProfileSummaries || []);
export const createProfile = (name, description, copyFrom) => B("POST", "/inference-profiles", { body: { inferenceProfileName: name, ...(description ? { description } : {}), modelSource: { copyFrom } } });
export const deleteProfile = (id) => B("DELETE", `/inference-profiles/${enc(id)}`);

// batch inference
export const listBatchJobs = () => B("GET", "/model-invocation-jobs", { query: { maxResults: "1000" } }).then((r) => r.invocationJobSummaries || []);
export const createBatchJob = (jobName, modelId, input, output) => B("POST", "/model-invocation-job", { body: {
  jobName, modelId, roleArn: roleArn(), inputDataConfig: { s3InputDataConfig: { s3Uri: input } }, outputDataConfig: { s3OutputDataConfig: { s3Uri: output } } } });
export const stopBatchJob = (arn) => B("POST", `/model-invocation-job/${enc(arn)}/stop`);

// provisioned throughput
export const listProvisioned = () => B("GET", "/provisioned-model-throughputs", { query: { maxResults: "1000" } }).then((r) => r.provisionedModelSummaries || []);
export const createProvisioned = (name, modelId, units, term) => B("POST", "/provisioned-model-throughput", { body: { provisionedModelName: name, modelId, modelUnits: Number(units), ...(term ? { commitmentDuration: term } : {}) } });
export const deleteProvisioned = (arn) => B("DELETE", `/provisioned-model-throughput/${enc(arn)}`);

// custom models + customization jobs
export const listCustomModels = () => B("GET", "/custom-models", { query: { maxResults: "1000" } }).then((r) => r.modelSummaries || []);
export const deleteCustomModel = (arn) => B("DELETE", `/custom-models/${enc(arn)}`);
export const listCustomizationJobs = () => B("GET", "/model-customization-jobs", { query: { maxResults: "1000" } }).then((r) => r.modelCustomizationJobSummaries || []);
export const createCustomizationJob = (jobName, customModelName, base, trainUri, outUri, epochs) => B("POST", "/model-customization-jobs", { body: {
  jobName, customModelName, roleArn: roleArn(), baseModelIdentifier: base, customizationType: "FINE_TUNING",
  trainingDataConfig: { s3Uri: trainUri }, outputDataConfig: { s3Uri: outUri }, hyperParameters: { epochCount: String(epochs || 1) } } });
export const stopCustomizationJob = (arn) => B("POST", `/model-customization-jobs/${enc(arn)}/stop`);

// prompt routers
export const listRouters = (type) => B("GET", "/prompt-routers", { query: { type, maxResults: "100" } }).then((r) => r.promptRouterSummaries || []);
export const createRouter = (name, models, quality, fallback, description) => B("POST", "/prompt-routers", { body: {
  promptRouterName: name, ...(description ? { description } : {}), models: models.map((m) => ({ modelArn: m })), routingCriteria: { responseQualityDifference: Number(quality) }, fallbackModel: { modelArn: fallback } } });
export const deleteRouter = (arn) => B("DELETE", `/prompt-routers/${enc(arn)}`);

// marketplace deployments
export const listEndpoints = () => B("GET", "/marketplace-model/endpoints", { query: { maxResults: "100" } }).then((r) => r.marketplaceModelEndpoints || []);
export const registerEndpoint = (endpointArn, modelSourceIdentifier) => B("POST", `/marketplace-model/endpoints/${enc(endpointArn)}/registration`, { body: { modelSourceIdentifier } });
export const deregisterEndpoint = (endpointArn) => B("DELETE", `/marketplace-model/endpoints/${enc(endpointArn)}/registration`);
export const deleteEndpoint = (arn) => B("DELETE", `/marketplace-model/endpoints/${enc(arn)}`);
