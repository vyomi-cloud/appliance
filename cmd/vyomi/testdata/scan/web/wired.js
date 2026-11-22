// A file that already points the SDKs at a local simulator: the already-wired rule matches here.
const { S3Client } = require("@aws-sdk/client-s3");
const s3 = new S3Client({ endpoint: process.env.AWS_ENDPOINT_URL, forcePathStyle: true });
const storageHost = process.env.STORAGE_EMULATOR_HOST;
const pubsubHost = process.env.PUBSUB_EMULATOR_HOST;
module.exports = { s3, storageHost, pubsubHost };
