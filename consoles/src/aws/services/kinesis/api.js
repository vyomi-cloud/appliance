/* Kinesis Data Streams over the native JSON wire (X-Amz-Target Kinesis_20131202.*). */
import { awsJson } from "../../../common/wire.js";

const call = (op, body) => awsJson("kinesis", `Kinesis_20131202.${op}`, body, { version: "1.1" });

export const b64 = (s) => btoa(unescape(encodeURIComponent(s)));
export const unb64 = (s) => decodeURIComponent(escape(atob(s)));

export const ALL_METRICS = ["IncomingBytes", "IncomingRecords", "OutgoingBytes", "OutgoingRecords",
  "WriteProvisionedThroughputExceeded", "ReadProvisionedThroughputExceeded", "IteratorAgeMilliseconds"];

export const createStream = (input) => call("CreateStream", input);
export const deleteStream = (name, enforceConsumerDeletion) => call("DeleteStream", { StreamName: name, EnforceConsumerDeletion: !!enforceConsumerDeletion });
export const describeStreamSummary = (name) => call("DescribeStreamSummary", { StreamName: name }).then((r) => r.StreamDescriptionSummary);

export async function listStreams() {
  const out = [];
  let token;
  do {
    const r = await call("ListStreams", token ? { ExclusiveStartStreamName: token } : {});
    out.push(...(r.StreamSummaries || []));
    token = r.HasMoreStreams ? out[out.length - 1].StreamName : undefined;
  } while (token);
  return out;
}

export async function listShards(name) {
  const out = [];
  let token;
  do {
    const r = await call("ListShards", token ? { StreamName: name, NextToken: token } : { StreamName: name });
    out.push(...(r.Shards || []));
    token = r.NextToken;
  } while (token);
  return out;
}

export const updateShardCount = (name, targetShardCount) => call("UpdateShardCount", { StreamName: name, TargetShardCount: targetShardCount, ScalingType: "UNIFORM_SCALING" });
export const updateStreamMode = (arn, mode) => call("UpdateStreamMode", { StreamARN: arn, StreamModeDetails: { StreamMode: mode } });

export const increaseRetention = (name, hours) => call("IncreaseStreamRetentionPeriod", { StreamName: name, RetentionPeriodHours: hours });
export const decreaseRetention = (name, hours) => call("DecreaseStreamRetentionPeriod", { StreamName: name, RetentionPeriodHours: hours });
export const setRetention = (name, current, hours) => (hours === current ? Promise.resolve() : hours > current ? increaseRetention(name, hours) : decreaseRetention(name, hours));

export const startEncryption = (name, keyId) => call("StartStreamEncryption", { StreamName: name, EncryptionType: "KMS", KeyId: keyId });
export const stopEncryption = (name) => call("StopStreamEncryption", { StreamName: name, EncryptionType: "KMS" });

export const enableMonitoring = (name, metrics) => call("EnableEnhancedMonitoring", { StreamName: name, ShardLevelMetrics: metrics });
export const disableMonitoring = (name, metrics) => call("DisableEnhancedMonitoring", { StreamName: name, ShardLevelMetrics: metrics });

export const listTagsForStream = (name) => call("ListTagsForStream", { StreamName: name }).then((r) => r.Tags || []);
export const addTagsToStream = (name, tags) => call("AddTagsToStream", { StreamName: name, Tags: tags });
export const removeTagsFromStream = (name, keys) => call("RemoveTagsFromStream", { StreamName: name, TagKeys: keys });

export const getResourcePolicy = (resourceArn) => call("GetResourcePolicy", { ResourceARN: resourceArn }).then((r) => r.Policy).catch((e) => (e.code === "ResourceNotFoundException" ? "{}" : Promise.reject(e)));
export const putResourcePolicy = (resourceArn, policy) => call("PutResourcePolicy", { ResourceARN: resourceArn, Policy: policy });

export const putRecord = (name, data, partitionKey) => call("PutRecord", { StreamName: name, Data: data, PartitionKey: partitionKey });
export const getShardIterator = (name, shardId, type, extra) => call("GetShardIterator", { StreamName: name, ShardId: shardId, ShardIteratorType: type, ...extra }).then((r) => r.ShardIterator);
export const getRecords = (shardIterator, limit) => call("GetRecords", { ShardIterator: shardIterator, Limit: limit || 25 });

export const registerConsumer = (streamArn, consumerName) => call("RegisterStreamConsumer", { StreamARN: streamArn, ConsumerName: consumerName }).then((r) => r.Consumer);
export const deregisterConsumer = (streamArn, consumerName) => call("DeregisterStreamConsumer", { StreamARN: streamArn, ConsumerName: consumerName });
export const listConsumers = (streamArn) => call("ListStreamConsumers", { StreamARN: streamArn }).then((r) => r.Consumers || []);

export const capacityLabel = (mode) => (mode?.StreamMode === "ON_DEMAND" ? "On-demand" : "Provisioned");
