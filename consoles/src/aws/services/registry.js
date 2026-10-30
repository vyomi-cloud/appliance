/* AWS lens service registry. One entry per service; `load` lazy-imports the service module
 * (its own chunk). A service module exports default {nav, routes} — see s3/index.jsx.
 * Services without a v4 module yet stay reachable through the classic (v3) console.
 * `icon` names Vyomi's own original tile (common/icons/aws.js) — no AWS Architecture Icons. */

export const CATEGORIES = ["Compute", "Storage", "Database", "Networking & Content Delivery", "Security, Identity, & Compliance", "Application Integration", "Management & Governance"];

export const SERVICES = [
  { id: "s3", icon: "s3", title: "S3", description: "Scalable storage in the cloud", category: "Storage", load: () => import("./s3/index.jsx") },
  { id: "dynamodb", icon: "dynamodb", title: "DynamoDB", description: "Managed NoSQL database", category: "Database", load: () => import("./dynamodb/index.jsx") },
  { id: "ec2", icon: "ec2", title: "EC2", description: "Virtual servers in the cloud", category: "Compute", classic: "ec2" },
  { id: "lambda", icon: "lambda", title: "Lambda", description: "Run code without thinking about servers", category: "Compute", classic: "lambda" },
  { id: "rds", icon: "rds", title: "RDS", description: "Managed relational database service", category: "Database", classic: "rds" },
  { id: "vpc", icon: "vpc", title: "VPC", description: "Isolated cloud resources", category: "Networking & Content Delivery", classic: "vpc" },
  { id: "apigateway", icon: "apigateway", title: "API Gateway", description: "Build, deploy, and manage APIs", category: "Networking & Content Delivery", classic: "apigateway" },
  { id: "iam", icon: "iam", title: "IAM", description: "Manage access to AWS resources", category: "Security, Identity, & Compliance", classic: "iam" },
  { id: "kms", icon: "kms", title: "Key Management Service", description: "Create and control encryption keys", category: "Security, Identity, & Compliance", load: () => import("./kms/index.jsx") },
  { id: "secretsmanager", icon: "secretsmanager", title: "Secrets Manager", description: "Store, manage, and retrieve secrets", category: "Security, Identity, & Compliance", classic: "secretsmanager" },
  { id: "sqs", icon: "sqs", title: "Simple Queue Service", description: "Managed message queues", category: "Application Integration", classic: "sqs" },
  { id: "sns", icon: "sns", title: "Simple Notification Service", description: "Pub/sub, SMS, email, and mobile push", category: "Application Integration", classic: "sns" },
  { id: "eventbridge", icon: "eventbridge", title: "EventBridge", description: "Serverless event bus", category: "Application Integration", classic: "eventbridge" },
  { id: "cloudwatch", icon: "cloudwatch", title: "CloudWatch", description: "Monitor resources and applications", category: "Management & Governance", classic: "cloudwatch" },
  { id: "cloudformation", icon: "cloudformation", title: "CloudFormation", description: "Create and manage resources with templates", category: "Management & Governance", classic: "cloudformation" },
];

export const byId = Object.fromEntries(SERVICES.map((s) => [s.id, s]));

/** Classic (v3) console deep link, used until a service has its v4 module. */
export const classicHref = (svc) => `${location.pathname.split("/v4/")[0]}/console/aws#${svc}`;
