/* GCP lens product registry. One entry per product Vyomi simulates; `load` lazy-imports
 * the product's v4 module ({nav, routes}, see storage/index.jsx). Products without a v4
 * module yet render an honest NotSimulated panel linking to the classic (v3) console. */
/* Material outline icons (Google's open-source Material Symbols set, Apache-2.0) — no Google Cloud product icons. */
import BucketIcon from "@mui/icons-material/esm/Inventory2Outlined.js";
import ComputeIcon from "@mui/icons-material/esm/MemoryOutlined.js";
import ClusterIcon from "@mui/icons-material/esm/HubOutlined.js";
import SqlIcon from "@mui/icons-material/esm/StorageOutlined.js";
import DocumentIcon from "@mui/icons-material/esm/DescriptionOutlined.js";
import NetworkIcon from "@mui/icons-material/esm/LanOutlined.js";
import RunIcon from "@mui/icons-material/esm/DirectionsRunOutlined.js";
import FunctionsIcon from "@mui/icons-material/esm/FunctionsOutlined.js";
import MessageIcon from "@mui/icons-material/esm/MessageOutlined.js";
import ScheduleIcon from "@mui/icons-material/esm/ScheduleOutlined.js";
import SecretIcon from "@mui/icons-material/esm/PasswordOutlined.js";
import KeyIcon from "@mui/icons-material/esm/VpnKeyOutlined.js";
import IamIcon from "@mui/icons-material/esm/AdminPanelSettingsOutlined.js";
import ArtifactIcon from "@mui/icons-material/esm/ViewInArOutlined.js";
import ChartIcon from "@mui/icons-material/esm/BarChartOutlined.js";
import LogIcon from "@mui/icons-material/esm/ArticleOutlined.js";
import { classicUrl } from "../../common/classic.js";

export const CATEGORIES = ["Compute", "Storage", "Databases", "Networking", "Serverless", "Integration Services", "Security", "Management", "CI/CD", "Observability"];

export const PRODUCTS = [
  { id: "storage", title: "Cloud Storage", description: "Object storage for companies of all sizes", category: "Storage", icon: BucketIcon, load: () => import("./storage/index.jsx") },
  { id: "compute", title: "Compute Engine", description: "VMs, GPUs, TPUs, disks", category: "Compute", icon: ComputeIcon, load: () => import("./compute/index.jsx") },
  { id: "kubernetes", title: "Kubernetes Engine", description: "Managed Kubernetes clusters", category: "Compute", icon: ClusterIcon, load: () => import("./kubernetes/index.jsx") },
  { id: "sql", title: "Cloud SQL", description: "Managed MySQL, PostgreSQL, SQL Server", category: "Databases", icon: SqlIcon, classic: "sql" },
  { id: "firestore", title: "Firestore", description: "Serverless NoSQL document database", category: "Databases", icon: DocumentIcon, load: () => import("./firestore/index.jsx") },
  { id: "networking", title: "VPC network", description: "Networks, subnets, firewall rules", category: "Networking", icon: NetworkIcon, load: () => import("./networking/index.jsx") },
  { id: "run", title: "Cloud Run", description: "Fully managed container platform", category: "Serverless", icon: RunIcon, classic: "run" },
  { id: "functions", title: "Cloud Functions", description: "Event-driven serverless functions", category: "Serverless", icon: FunctionsIcon, load: () => import("./functions/index.jsx") },
  { id: "pubsub", title: "Pub/Sub", description: "Global real-time messaging", category: "Integration Services", icon: MessageIcon, classic: "pubsub" },
  { id: "cloudscheduler", title: "Cloud Scheduler", description: "Fully managed cron job service", category: "Integration Services", icon: ScheduleIcon, load: () => import("./cloudscheduler/index.jsx") },
  { id: "security/secret-manager", title: "Secret Manager", description: "Store API keys, passwords and other secrets", category: "Security", icon: SecretIcon, classic: "secretmanager" },
  { id: "security/kms", title: "Cloud KMS", description: "Manage encryption keys", category: "Security", icon: KeyIcon, load: () => import("./security/kms/index.jsx") },
  { id: "iam-admin", title: "IAM & Admin", description: "Resource access control", category: "Management", icon: IamIcon, load: () => import("./iam-admin/index.jsx") },
  { id: "artifacts", title: "Artifact Registry", description: "Store, manage and secure container images and packages", category: "CI/CD", icon: ArtifactIcon, load: () => import("./artifacts/index.jsx") },
  { id: "monitoring", title: "Monitoring", description: "Metrics, dashboards, alerting, uptime checks", category: "Observability", icon: ChartIcon, load: () => import("./monitoring/index.jsx") },
  { id: "logs", title: "Logging", description: "Logs Explorer, routing and storage", category: "Observability", icon: LogIcon, load: () => import("./logs/index.jsx") },
];

export const byId = Object.fromEntries(PRODUCTS.map((p) => [p.id, p]));

/** Find the product a route path belongs to (ids may span two segments, e.g. security/kms). */
export function productFor(parts) {
  return byId[parts.slice(0, 2).join("/")] || byId[parts[0]] || null;
}

/** Classic (v3) console deep link, used until a product has its v4 module. */
export const classicHref = (svc) => classicUrl("gcp", svc);
