// Nano savings: what each resource would cost per month on the real cloud at public
// list prices (the in-browser simulator costs $0). Keys are the census's by_service keys
// (/api/runtime/host-distribution). ONE table for the Spaces page and the AWS / GCP /
// Azure consoles, so a space card and its console always show the same number; a key
// missing here is priced at $1.00/mo by both, so add new services here.
window.NANO_RATE = {
  // AWS
  s3: 0.5, dynamodb: 1.25, kms: 1, secretsmanager: 0.4,
  sqs: 0.4, sns: 0.5, iam: 0, rds: 25.55,
  elbv2: 16.43, ec2: 30.37, lambda: 0.2, apigateway: 3.5,
  vpc: 0, cloudwatch: 0.1, ssm: 0.05,
  // GCP
  compute: 24.53, storage: 0.5, cloudsql: 25, pubsub: 0.4,
  firestore: 0.18, functions: 0.2, secretmanager: 0.18,
  // Azure — ARM resource types (Azure console, VMs, storage accounts, …)
  'microsoft.compute/virtualmachines': 30.37, 'microsoft.sql/servers': 4.99, 'microsoft.storage/storageaccounts': 0.5, 'microsoft.documentdb/databaseaccounts': 24.48,
  'microsoft.web/sites': 0.2, 'microsoft.servicebus/namespaces': 9.81, 'microsoft.keyvault/vaults': 0.03,
  // Azure — data-plane cores (blob containers, queues, Cosmos, Key Vault, Service Bus, SQL, RBAC)
  blobcontainers: 0.02, queues: 0.05, cosmosdbs: 23.36, kvsecrets: 0.03,
  kvkeys: 0.03, servicebus: 9.81, azuresql: 4.99, azurerbac: 0,
};
