/* GCP lens product registry. One entry per product Vyomi simulates; `load` lazy-imports
 * the product's v4 module ({nav, routes}, see storage/index.jsx). Products without a v4
 * module yet render an honest NotSimulated panel linking to the classic (v3) console. */
import StorageIcon from "@mui/icons-material/esm/Storage.js";
import MemoryIcon from "@mui/icons-material/esm/Memory.js";
import DnsIcon from "@mui/icons-material/esm/Dns.js";
import InsertDriveFileIcon from "@mui/icons-material/esm/InsertDriveFile.js";
import MessageIcon from "@mui/icons-material/esm/Message.js";
import LockIcon from "@mui/icons-material/esm/Lock.js";
import VpnKeyIcon from "@mui/icons-material/esm/VpnKey.js";
import SecurityIcon from "@mui/icons-material/esm/Security.js";
import LanIcon from "@mui/icons-material/esm/Lan.js";
import BoltIcon from "@mui/icons-material/esm/Bolt.js";
import FunctionsIcon from "@mui/icons-material/esm/Functions.js";
import InventoryIcon from "@mui/icons-material/esm/Inventory.js";
import ScheduleIcon from "@mui/icons-material/esm/Schedule.js";
import HubIcon from "@mui/icons-material/esm/Hub.js";
import BarChartIcon from "@mui/icons-material/esm/BarChart.js";
import ArticleIcon from "@mui/icons-material/esm/Article.js";

export const CATEGORIES = ["Compute", "Storage", "Databases", "Networking", "Serverless", "Integration Services", "Security", "Management", "CI/CD", "Observability"];

export const PRODUCTS = [
  { id: "storage", title: "Cloud Storage", description: "Object storage for companies of all sizes", category: "Storage", icon: StorageIcon, load: () => import("./storage/index.jsx") },
  { id: "compute", title: "Compute Engine", description: "VMs, GPUs, TPUs, disks", category: "Compute", icon: MemoryIcon, classic: "compute" },
  { id: "kubernetes", title: "Kubernetes Engine", description: "Managed Kubernetes clusters", category: "Compute", icon: HubIcon, classic: "gke" },
  { id: "sql", title: "Cloud SQL", description: "Managed MySQL, PostgreSQL, SQL Server", category: "Databases", icon: DnsIcon, classic: "sql" },
  { id: "firestore", title: "Firestore", description: "Serverless NoSQL document database", category: "Databases", icon: InsertDriveFileIcon, classic: "firestore" },
  { id: "networking", title: "VPC network", description: "Networks, subnets, firewall rules", category: "Networking", icon: LanIcon, classic: "vpc" },
  { id: "run", title: "Cloud Run", description: "Fully managed container platform", category: "Serverless", icon: BoltIcon, classic: "run" },
  { id: "functions", title: "Cloud Functions", description: "Event-driven serverless functions", category: "Serverless", icon: FunctionsIcon, classic: "functions" },
  { id: "pubsub", title: "Pub/Sub", description: "Global real-time messaging", category: "Integration Services", icon: MessageIcon, classic: "pubsub" },
  { id: "cloudscheduler", title: "Cloud Scheduler", description: "Fully managed cron job service", category: "Integration Services", icon: ScheduleIcon, classic: "scheduler" },
  { id: "security/secret-manager", title: "Secret Manager", description: "Store API keys, passwords and other secrets", category: "Security", icon: LockIcon, classic: "secretmanager" },
  { id: "security/kms", title: "Cloud KMS", description: "Manage encryption keys", category: "Security", icon: VpnKeyIcon, classic: "kms" },
  { id: "iam-admin", title: "IAM & Admin", description: "Resource access control", category: "Management", icon: SecurityIcon, classic: "iam" },
  { id: "artifacts", title: "Artifact Registry", description: "Store, manage and secure container images and packages", category: "CI/CD", icon: InventoryIcon, classic: "artifactregistry" },
  { id: "monitoring", title: "Monitoring", description: "Metrics, dashboards, alerting, uptime checks", category: "Observability", icon: BarChartIcon, classic: "monitoring" },
  { id: "logs", title: "Logging", description: "Logs Explorer, routing and storage", category: "Observability", icon: ArticleIcon, classic: "logging" },
];

export const byId = Object.fromEntries(PRODUCTS.map((p) => [p.id, p]));

/** Find the product a route path belongs to (ids may span two segments, e.g. security/kms). */
export function productFor(parts) {
  return byId[parts.slice(0, 2).join("/")] || byId[parts[0]] || null;
}

/** Classic (v3) console deep link, used until a product has its v4 module. */
export const classicHref = (svc) => `${location.pathname.split("/v4/")[0]}/console/gcp${svc ? "#" + svc : ""}`;
