import SecurityIcon from "@mui/icons-material/esm/SecurityOutlined.js";
import Findings from "./Findings.jsx";

export default {
  nav: [{ text: "Findings", href: "#/security/scc", icon: SecurityIcon, match: ["#/security/scc"] }],
  routes: [{ pattern: "/security/scc", component: Findings }],
};
