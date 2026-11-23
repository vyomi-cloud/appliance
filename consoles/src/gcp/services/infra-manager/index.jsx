import AccountTreeIcon from "@mui/icons-material/esm/AccountTreeOutlined.js";
import Deployments from "./Deployments.jsx";
import CreateDeployment from "./CreateDeployment.jsx";
import DeploymentDetail from "./DeploymentDetail.jsx";
import ExportTerraform from "./ExportTerraform.jsx";

export default {
  nav: [{ text: "Deployments", href: "#/infra-manager", icon: AccountTreeIcon, match: ["#/infra-manager"] }],
  routes: [
    { pattern: "/infra-manager", component: Deployments },
    { pattern: "/infra-manager/deployments/new", component: CreateDeployment },
    { pattern: "/infra-manager/export", component: ExportTerraform },
    { pattern: "/infra-manager/deployments/:region/:name", component: DeploymentDetail },
    { pattern: "/infra-manager/deployments/:region/:name/edit", component: CreateDeployment },
  ],
};
