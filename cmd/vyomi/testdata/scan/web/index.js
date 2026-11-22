// Node.js: AWS SDK v3, Google Cloud and Azure clients.
const { S3Client } = require("@aws-sdk/client-s3");
const { SQSClient } = require("@aws-sdk/client-sqs");
const { DynamoDBClient } = require("@aws-sdk/client-dynamodb");
const { PubSub } = require("@google-cloud/pubsub");
const { Storage } = require("@google-cloud/storage");
const { BlobServiceClient } = require("@azure/storage-blob");
const { ServiceBusClient } = require("@azure/service-bus");
const { CosmosClient } = require("@azure/cosmos");

module.exports = { S3Client, SQSClient, DynamoDBClient, PubSub, Storage, BlobServiceClient, ServiceBusClient, CosmosClient };
