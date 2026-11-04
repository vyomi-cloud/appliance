/* Amazon ECR control plane over its native JSON 1.1 wire (SigV4 scope `ecr`) -> core/ecr_core.py. */
import { awsJson } from "../../../common/wire.js";

const E = (op, body = {}) => awsJson("ecr", `AmazonEC2ContainerRegistry_V20150921.${op}`, body, { version: "1.1" });

async function paged(op, body, key) {
  const out = []; let nextToken;
  do { const r = await E(op, { ...body, nextToken }); out.push(...(r[key] || [])); nextToken = r.nextToken; } while (nextToken);
  return out;
}
const none = (p) => p.catch((e) => { if (/NotFound/.test(e.code || "")) return null; throw e; });

export const listRepositories = () => paged("DescribeRepositories", {}, "repositories");
export const getRepository = async (name) => (await E("DescribeRepositories", { repositoryNames: [name] })).repositories[0];
export const createRepository = (name, { mutability = "MUTABLE", scanOnPush = false, kmsKey } = {}) => E("CreateRepository", {
  repositoryName: name, imageTagMutability: mutability, imageScanningConfiguration: { scanOnPush },
  encryptionConfiguration: kmsKey ? { encryptionType: "KMS", kmsKey } : { encryptionType: "AES256" } });
export const deleteRepository = (name, force) => E("DeleteRepository", { repositoryName: name, force: !!force });
export const putTagMutability = (name, imageTagMutability) => E("PutImageTagMutability", { repositoryName: name, imageTagMutability });
export const putScanOnPush = (name, scanOnPush) => E("PutImageScanningConfiguration", { repositoryName: name, imageScanningConfiguration: { scanOnPush } });

export const listImages = (name) => paged("DescribeImages", { repositoryName: name }, "imageDetails");
export const deleteImages = (name, digests) => E("BatchDeleteImage", { repositoryName: name, imageIds: digests.map((imageDigest) => ({ imageDigest })) });
export const startScan = (name, imageDigest) => E("StartImageScan", { repositoryName: name, imageId: { imageDigest } });
export const scanFindings = (name, imageDigest) => none(E("DescribeImageScanFindings", { repositoryName: name, imageId: { imageDigest }, maxResults: 1000 }));

export const getLifecycle = (name) => none(E("GetLifecyclePolicy", { repositoryName: name }));
export const putLifecycle = (name, lifecyclePolicyText) => E("PutLifecyclePolicy", { repositoryName: name, lifecyclePolicyText });
export const deleteLifecycle = (name) => E("DeleteLifecyclePolicy", { repositoryName: name });
export const startPreview = (name, lifecyclePolicyText) => E("StartLifecyclePolicyPreview", { repositoryName: name, lifecyclePolicyText });
export const getPreview = (name) => none(E("GetLifecyclePolicyPreview", { repositoryName: name }));

export const getRepoPolicy = (name) => none(E("GetRepositoryPolicy", { repositoryName: name }));
export const setRepoPolicy = (name, policyText) => E("SetRepositoryPolicy", { repositoryName: name, policyText });
export const deleteRepoPolicy = (name) => E("DeleteRepositoryPolicy", { repositoryName: name });

export const describeRegistry = () => E("DescribeRegistry");
export const putReplication = (rules) => E("PutReplicationConfiguration", { replicationConfiguration: { rules } });
export const getScanning = () => E("GetRegistryScanningConfiguration");
export const putScanning = (scanType, rules) => E("PutRegistryScanningConfiguration", { scanType, rules });
export const getRegistryPolicy = () => none(E("GetRegistryPolicy"));
export const putRegistryPolicy = (policyText) => E("PutRegistryPolicy", { policyText });
export const deleteRegistryPolicy = () => E("DeleteRegistryPolicy");
