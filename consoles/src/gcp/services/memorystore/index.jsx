import InventoryIcon from "@mui/icons-material/esm/Inventory.js";
import Instances from "./Instances.jsx";
import CreateInstance from "./CreateInstance.jsx";
import InstanceOverview from "./InstanceOverview.jsx";
import Connections from "./Connections.jsx";
import Configuration from "./Configuration.jsx";
import Nodes from "./Nodes.jsx";
import Maintenance from "./Maintenance.jsx";

export default {
  nav: [
    { text: "Instances", href: "#/memorystore", icon: InventoryIcon, match: ["#/memorystore/create", "#/memorystore/instances"] },
  ],
  routes: [
    { pattern: "/memorystore", component: Instances },
    { pattern: "/memorystore/create", component: CreateInstance },
    { pattern: "/memorystore/instances/:location/:id/overview", component: InstanceOverview },
    { pattern: "/memorystore/instances/:location/:id/connections", component: Connections },
    { pattern: "/memorystore/instances/:location/:id/configuration", component: Configuration },
    { pattern: "/memorystore/instances/:location/:id/nodes", component: Nodes },
    { pattern: "/memorystore/instances/:location/:id/maintenance", component: Maintenance },
  ],
};
