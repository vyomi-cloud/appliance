/* Azure lens service registry. One entry per service Vyomi simulates; `load` lazy-imports the
 * service's v4 module (default export {routes, ...} — see storage/index.jsx). Services without a
 * v4 module yet render an honest NotSimulated blade linking to the classic (v3) console.
 * `glyph` is a neutral initials badge (Vyomi ships no Microsoft service icons). */

export const CATEGORIES = ["Compute", "Containers", "Databases", "Storage", "Networking", "Integration", "Security", "Identity", "Management and governance"];

export const SERVICES = [
  { id: "storage", title: "Storage accounts", type: "Microsoft.Storage/storageAccounts", category: "Storage", glyph: ["SA", "#0b7a75"], load: () => import("./storage/index.jsx") },
  { id: "vms", title: "Virtual machines", type: "Microsoft.Compute/virtualMachines", category: "Compute", glyph: ["VM", "#2266e3"] },
  { id: "sql", title: "SQL databases", type: "Microsoft.Sql/servers/databases", category: "Databases", glyph: ["SQ", "#5c2d91"] },
  { id: "cosmos", title: "Azure Cosmos DB", type: "Microsoft.DocumentDB/databaseAccounts", category: "Databases", glyph: ["CD", "#3a5aa8"] },
  { id: "keyvaults", title: "Key vaults", type: "Microsoft.KeyVault/vaults", category: "Security", glyph: ["KV", "#a67c00"] },
  { id: "servicebus", title: "Service Bus", type: "Microsoft.ServiceBus/namespaces", category: "Integration", glyph: ["SB", "#1f6f8b"] },
  { id: "functionapp", title: "Function App", type: "Microsoft.Web/sites (functionapp)", category: "Compute", glyph: ["FN", "#c26d00"] },
  { id: "appservices", title: "App Services", type: "Microsoft.Web/sites", category: "Compute", glyph: ["AS", "#1c74c4"] },
  { id: "vnets", title: "Virtual networks", type: "Microsoft.Network/virtualNetworks", category: "Networking", glyph: ["VN", "#3b7d23"] },
  { id: "nsgs", title: "Network security groups", type: "Microsoft.Network/networkSecurityGroups", category: "Networking", glyph: ["NS", "#4d7d2d"] },
  { id: "resourcegroups", title: "Resource groups", type: "Microsoft.Resources/resourceGroups", category: "Management and governance", glyph: ["RG", "#4b6584"] },
  { id: "acr", title: "Container registries", type: "Microsoft.ContainerRegistry/registries", category: "Containers", glyph: ["CR", "#0a6e9e"] },
  { id: "aks", title: "Kubernetes services", type: "Microsoft.ContainerService/managedClusters", category: "Containers", glyph: ["K8", "#3c4aa3"] },
  { id: "apim", title: "API Management services", type: "Microsoft.ApiManagement/service", category: "Integration", glyph: ["AP", "#4f6bed"] },
  { id: "eventgrid", title: "Event Grid", type: "Microsoft.EventGrid/topics", category: "Integration", glyph: ["EG", "#a23e8d"] },
  { id: "monitor", title: "Monitor", type: "Microsoft.Insights", category: "Management and governance", glyph: ["MO", "#2d7d9a"] },
  { id: "entra", title: "Microsoft Entra ID", type: "Identity", category: "Identity", glyph: ["ID", "#2f5bb7"] },
  { id: "subscriptions", title: "Subscriptions", type: "Microsoft.Resources/subscriptions", category: "Management and governance", glyph: ["SU", "#8a6d00"] },
  { id: "cost", title: "Cost Management", type: "Microsoft.CostManagement", category: "Management and governance", glyph: ["CM", "#3d8b37"] },
];

export const byId = Object.fromEntries(SERVICES.map((s) => [s.id, s]));

/** Home "Azure services" strip (the portal shows a short, ordered set + "More services"). */
export const HOME_TILES = ["storage", "vms", "sql", "cosmos", "functionapp", "appservices", "aks", "keyvaults"];

/** Classic (v3) Azure console, used until a service has its v4 module. */
export const classicHref = () => `${location.pathname.split("/v4/")[0]}/console/azure`;
