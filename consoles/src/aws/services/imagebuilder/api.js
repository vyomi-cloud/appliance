/* EC2 Image Builder over its native REST-JSON wire (SigV4 scope `imagebuilder`) -> core/imagebuilder_core.py. */
import { awsRest } from "../../../common/wire.js";

const R = (method, op, opts) => awsRest("imagebuilder", method, `/${op}`, opts);
const q = (query) => ({ query });

export const listPipelines = () => R("POST", "ListImagePipelines", { body: {} }).then((r) => r.imagePipelineList || []);
export const getPipeline = (arn) => R("GET", "GetImagePipeline", q({ imagePipelineArn: arn })).then((r) => r.imagePipeline);
export const createPipeline = (b) => R("PUT", "CreateImagePipeline", { body: b });
export const updatePipeline = (b) => R("PUT", "UpdateImagePipeline", { body: b });
export const deletePipeline = (arn) => R("DELETE", "DeleteImagePipeline", q({ imagePipelineArn: arn }));
export const runPipeline = (arn) => R("PUT", "StartImagePipelineExecution", { body: { imagePipelineArn: arn } });
export const pipelineImages = (arn) => R("POST", "ListImagePipelineImages", { body: { imagePipelineArn: arn } }).then((r) => r.imageSummaryList || []);

export async function listImageBuilds() {
  const versions = (await R("POST", "ListImages", { body: {} })).imageVersionList || [];
  const out = [];
  for (const v of versions) out.push(...((await R("POST", "ListImageBuildVersions", { body: { imageVersionArn: v.arn } })).imageSummaryList || []));
  return out.sort((a, b) => String(b.dateCreated).localeCompare(String(a.dateCreated)));
}
export const getImage = (arn) => R("GET", "GetImage", q({ imageBuildVersionArn: arn })).then((r) => r.image);
export const getImageLog = (arn) => R("GET", "VyomiGetImageBuildLog", q({ imageBuildVersionArn: arn }));
export const createImage = (b) => R("PUT", "CreateImage", { body: b });
export const deleteImage = (arn) => R("DELETE", "DeleteImage", q({ imageBuildVersionArn: arn }));
export const cancelImage = (arn) => R("PUT", "CancelImageCreation", { body: { imageBuildVersionArn: arn } });

export const listComponents = (owner = "Self") => R("POST", "ListComponents", { body: { owner } }).then((r) => r.componentVersionList || []);
export const getComponent = (arn) => R("GET", "GetComponent", q({ componentBuildVersionArn: arn })).then((r) => r.component);
export const createComponent = (b) => R("PUT", "CreateComponent", { body: b });
export const deleteComponent = (arn) => R("DELETE", "DeleteComponent", q({ componentBuildVersionArn: arn }));

export const listRecipes = () => R("POST", "ListImageRecipes", { body: {} }).then((r) => r.imageRecipeSummaryList || []);
export const getRecipe = (arn) => R("GET", "GetImageRecipe", q({ imageRecipeArn: arn })).then((r) => r.imageRecipe);
export const createRecipe = (b) => R("PUT", "CreateImageRecipe", { body: b });
export const deleteRecipe = (arn) => R("DELETE", "DeleteImageRecipe", q({ imageRecipeArn: arn }));

export const listInfra = () => R("POST", "ListInfrastructureConfigurations", { body: {} }).then((r) => r.infrastructureConfigurationSummaryList || []);
export const createInfra = (b) => R("PUT", "CreateInfrastructureConfiguration", { body: b });
export const deleteInfra = (arn) => R("DELETE", "DeleteInfrastructureConfiguration", q({ infrastructureConfigurationArn: arn }));

export const listDist = () => R("POST", "ListDistributionConfigurations", { body: {} }).then((r) => r.distributionConfigurationSummaryList || []);
export const createDist = (b) => R("PUT", "CreateDistributionConfiguration", { body: b });
export const deleteDist = (arn) => R("DELETE", "DeleteDistributionConfiguration", q({ distributionConfigurationArn: arn }));
