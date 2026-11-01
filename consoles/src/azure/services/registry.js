/* Azure lens service registry. One entry per service Vyomi simulates; `load` lazy-imports the
 * service's v4 module (default export {routes, ...} — see storage/index.jsx). Services without a
 * v4 module yet render an honest NotSimulated blade linking to the classic (v3) console.
 * `icon` names Vyomi's own original glyph (common/icons/azure.js) — no Microsoft service icons. */
import { classicUrl } from "../../common/classic.js";

export const CATEGORIES = ["Compute", "Containers", "Databases", "Storage", "Networking", "Integration", "Security", "Identity", "AI + machine learning", "Management and governance"];

export const SERVICES = [
  { id: "storage", title: "Storage accounts", type: "Microsoft.Storage/storageAccounts", category: "Storage", icon: "storage", load: () => import("./storage/index.jsx") },
  { id: "vms", title: "Virtual machines", type: "Microsoft.Compute/virtualMachines", category: "Compute", icon: "vms", load: () => import("./vms/index.jsx") },
  { id: "sql", title: "SQL databases", type: "Microsoft.Sql/servers/databases", category: "Databases", icon: "sql", load: () => import("./sql/index.jsx") },
  { id: "cosmos", title: "Azure Cosmos DB", type: "Microsoft.DocumentDB/databaseAccounts", category: "Databases", icon: "cosmos", load: () => import("./cosmos/index.jsx") },
  { id: "keyvaults", title: "Key vaults", type: "Microsoft.KeyVault/vaults", category: "Security", icon: "keyvaults", load: () => import("./keyvaults/index.jsx") },
  { id: "servicebus", title: "Service Bus", type: "Microsoft.ServiceBus/namespaces", category: "Integration", icon: "servicebus", load: () => import("./servicebus/index.jsx") },
  { id: "functionapp", title: "Function App", type: "Microsoft.Web/sites (functionapp)", category: "Compute", icon: "functionapp", load: () => import("./functionapp/index.jsx") },
  { id: "appservices", title: "App Services", type: "Microsoft.Web/sites", category: "Compute", icon: "appservices", load: () => import("./appservices/index.jsx") },
  { id: "vnets", title: "Virtual networks", type: "Microsoft.Network/virtualNetworks", category: "Networking", icon: "vnets", load: () => import("./vnets/index.jsx") },
  { id: "nsgs", title: "Network security groups", type: "Microsoft.Network/networkSecurityGroups", category: "Networking", icon: "nsgs", load: () => import("./nsgs/index.jsx") },
  { id: "dns", title: "DNS zones", type: "Microsoft.Network/dnszones", category: "Networking", icon: "dns", load: () => import("./dns/index.jsx") },
  { id: "resourcegroups", title: "Resource groups", type: "Microsoft.Resources/resourceGroups", category: "Management and governance", icon: "resourcegroups", load: () => import("./resourcegroups/index.jsx") },
  { id: "acr", title: "Container registries", type: "Microsoft.ContainerRegistry/registries", category: "Containers", icon: "acr", load: () => import("./acr/index.jsx") },
  { id: "aks", title: "Kubernetes services", type: "Microsoft.ContainerService/managedClusters", category: "Containers", icon: "aks", load: () => import("./aks/index.jsx") },
  { id: "apim", title: "API Management services", type: "Microsoft.ApiManagement/service", category: "Integration", icon: "apim", load: () => import("./apim/index.jsx") },
  { id: "eventgrid", title: "Event Grid", type: "Microsoft.EventGrid/topics", category: "Integration", icon: "eventgrid", load: () => import("./eventgrid/index.jsx") },
  { id: "monitor", title: "Monitor", type: "Microsoft.Insights", category: "Management and governance", icon: "monitor", load: () => import("./monitor/index.jsx") },
  { id: "defender", title: "Microsoft Defender for Cloud", type: "Microsoft.Security", category: "Security", icon: "defender", load: () => import("./defender/index.jsx") },
  { id: "entra", title: "Microsoft Entra ID", type: "Identity", category: "Identity", icon: "entra", load: () => import("./entra/index.jsx") },
  { id: "subscriptions", title: "Subscriptions", type: "Microsoft.Resources/subscriptions", category: "Management and governance", icon: "subscriptions", load: () => import("./subscriptions/index.jsx") },
  { id: "cost", title: "Cost Management", type: "Microsoft.CostManagement", category: "Management and governance", icon: "cost", load: () => import("./cost/index.jsx") },
  { id: "cognitiveservices", title: "Azure AI services", type: "Microsoft.CognitiveServices/accounts", category: "AI + machine learning", icon: "cognitiveservices", load: () => import("./cognitiveservices/index.jsx") },
];

export const byId = Object.fromEntries(SERVICES.map((s) => [s.id, s]));

/** Home "Azure services" strip (the portal shows a short, ordered set + "More services"). */
export const HOME_TILES = ["storage", "vms", "sql", "cosmos", "functionapp", "appservices", "aks", "keyvaults"];

/** Classic (v3) Azure console, used until a service has its v4 module. */
export const classicHref = () => classicUrl("azure");
