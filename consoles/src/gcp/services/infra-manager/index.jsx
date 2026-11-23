import AccountTreeIcon from "@mui/icons-material/esm/AccountTreeOutlined.js";
import Deployments from "./Deployments.jsx";

export default {
  nav: [{ text: "Deployments", href: "#/infra-manager", icon: AccountTreeIcon, match: ["#/infra-manager"] }],
  routes: [{ pattern: "/infra-manager", component: Deployments }],
};
