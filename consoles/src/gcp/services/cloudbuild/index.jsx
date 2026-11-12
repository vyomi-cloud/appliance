import BuildIcon from "@mui/icons-material/esm/BuildOutlined.js";
import Builds from "./Builds.jsx";

export default {
  nav: [{ text: "Builds", href: "#/cloudbuild", icon: BuildIcon, match: ["#/cloudbuild"] }],
  routes: [{ pattern: "/cloudbuild", component: Builds }],
};
