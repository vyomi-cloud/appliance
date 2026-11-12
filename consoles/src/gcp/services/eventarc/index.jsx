import EventIcon from "@mui/icons-material/esm/BoltOutlined.js";
import Triggers from "./Triggers.jsx";
import CreateTrigger from "./CreateTrigger.jsx";
import TriggerDetail from "./TriggerDetail.jsx";

export default {
  nav: [
    { text: "Triggers", href: "#/eventarc", icon: EventIcon, match: ["#/eventarc/triggers"] },
  ],
  routes: [
    { pattern: "/eventarc", component: Triggers },
    { pattern: "/eventarc/triggers", component: Triggers },
    { pattern: "/eventarc/triggers/new", component: CreateTrigger },
    { pattern: "/eventarc/triggers/:region/:name", component: TriggerDetail },
  ],
};
