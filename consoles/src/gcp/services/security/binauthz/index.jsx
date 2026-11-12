import VerifiedIcon from "@mui/icons-material/esm/VerifiedUserOutlined.js";
import BinAuthz from "./BinAuthz.jsx";

export default {
  nav: [{ text: "Binary Authorization", href: "#/security/binauthz", icon: VerifiedIcon, match: ["#/security/binauthz"] }],
  routes: [{ pattern: "/security/binauthz", component: BinAuthz }],
};
