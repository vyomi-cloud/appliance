import RocketIcon from "@mui/icons-material/esm/RocketLaunchOutlined.js";
import Pipelines from "./Pipelines.jsx";
import PipelineDetail from "./PipelineDetail.jsx";

export default {
  nav: [{ text: "Delivery pipelines", href: "#/clouddeploy", icon: RocketIcon, match: ["#/clouddeploy"] }],
  routes: [
    { pattern: "/clouddeploy", component: Pipelines },
    { pattern: "/clouddeploy/pipelines/:region/:name", component: PipelineDetail },
  ],
};
