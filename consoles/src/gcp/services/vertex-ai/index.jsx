import AutoAwesomeIcon from "@mui/icons-material/esm/AutoAwesomeOutlined.js";
import Studio from "./Studio.jsx";

export default {
  nav: [{ text: "Vertex AI Studio", href: "#/vertex-ai", icon: AutoAwesomeIcon, match: ["#/vertex-ai/studio"] }],
  routes: [
    { pattern: "/vertex-ai", component: Studio },
    { pattern: "/vertex-ai/studio", component: Studio },
  ],
};
