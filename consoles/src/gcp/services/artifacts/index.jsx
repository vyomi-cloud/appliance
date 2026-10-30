import InventoryIcon from "@mui/icons-material/esm/Inventory2Outlined.js";
import SettingsIcon from "@mui/icons-material/esm/SettingsOutlined.js";
import Repositories from "./Repositories.jsx";
import CreateRepository from "./CreateRepository.jsx";
import RepositoryDetail from "./RepositoryDetail.jsx";
import PackageDetail from "./PackageDetail.jsx";
import Settings from "./Settings.jsx";

export default {
  nav: [
    { text: "Repositories", href: "#/artifacts", icon: InventoryIcon, match: ["#/artifacts/create-repo", "#/artifacts/repo"] },
    { text: "Settings", href: "#/artifacts/settings", icon: SettingsIcon },
  ],
  routes: [
    { pattern: "/artifacts", component: Repositories },
    { pattern: "/artifacts/create-repo", component: CreateRepository },
    { pattern: "/artifacts/repo/:location/:name", component: RepositoryDetail },
    { pattern: "/artifacts/repo/:location/:name/package/:pkg", component: PackageDetail },
    { pattern: "/artifacts/settings", component: Settings },
  ],
};
