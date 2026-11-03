/* S3 Vectors native-wire calls (service s3vectors, rest-json; every operation is `POST /<Operation>`). */
import { awsRest } from "../../../common/wire.js";

const V = (op, body = {}) => awsRest("s3vectors", "POST", `/${op}`, { body });

export async function listVectorBuckets() {
  const out = []; let nextToken;
  do { const r = await V("ListVectorBuckets", { maxResults: 500, nextToken }); out.push(...(r.vectorBuckets || [])); nextToken = r.nextToken; } while (nextToken);
  return out;
}
export const createVectorBucket = (name, sseType = "AES256", kmsKeyArn) => V("CreateVectorBucket", {
  vectorBucketName: name, encryptionConfiguration: { sseType, ...(sseType === "aws:kms" && kmsKeyArn ? { kmsKeyArn } : {}) } });
export const deleteVectorBucket = (name) => V("DeleteVectorBucket", { vectorBucketName: name });
export const getVectorBucket = async (name) => (await V("GetVectorBucket", { vectorBucketName: name })).vectorBucket;
export async function getVectorBucketPolicy(name) {
  try { return (await V("GetVectorBucketPolicy", { vectorBucketName: name })).policy || ""; } catch (e) { if (e.status === 404) return ""; throw e; }
}
export const putVectorBucketPolicy = (name, policy) => V("PutVectorBucketPolicy", { vectorBucketName: name, policy });
export const deleteVectorBucketPolicy = (name) => V("DeleteVectorBucketPolicy", { vectorBucketName: name });

export async function listIndexes(bucket) {
  const out = []; let nextToken;
  do { const r = await V("ListIndexes", { vectorBucketName: bucket, maxResults: 500, nextToken }); out.push(...(r.indexes || [])); nextToken = r.nextToken; } while (nextToken);
  return out;
}
export const createIndex = (bucket, { name, dimension, metric, nonFilterable }) => V("CreateIndex", {
  vectorBucketName: bucket, indexName: name, dataType: "float32", dimension: Number(dimension), distanceMetric: metric,
  ...(nonFilterable?.length ? { metadataConfiguration: { nonFilterableMetadataKeys: nonFilterable } } : {}) });
export const getIndex = async (bucket, name) => (await V("GetIndex", { vectorBucketName: bucket, indexName: name })).index;
export const deleteIndex = (bucket, name) => V("DeleteIndex", { vectorBucketName: bucket, indexName: name });

export const listVectors = async (bucket, index, { nextToken } = {}) =>
  V("ListVectors", { vectorBucketName: bucket, indexName: index, maxResults: 100, returnData: true, returnMetadata: true, nextToken });
export const putVectors = (bucket, index, vectors) => V("PutVectors", { vectorBucketName: bucket, indexName: index, vectors });
export const deleteVectors = (bucket, index, keys) => V("DeleteVectors", { vectorBucketName: bucket, indexName: index, keys });
export const queryVectors = (bucket, index, { vector, topK, filter }) => V("QueryVectors", {
  vectorBucketName: bucket, indexName: index, queryVector: { float32: vector }, topK: Number(topK), returnDistance: true, returnMetadata: true,
  ...(filter ? { filter } : {}) });
