import SecretIcon from "@mui/icons-material/esm/PasswordOutlined.js";
import Secrets from "./Secrets.jsx";
import CreateSecret from "./CreateSecret.jsx";
import SecretDetail from "./SecretDetail.jsx";

export default {
  nav: [
    { text: "Secret Manager", href: "#/security/secret-manager", icon: SecretIcon, match: ["#/security/secret-manager/create", "#/security/secret-manager/secret"] },
  ],
  routes: [
    { pattern: "/security/secret-manager", component: Secrets },
    { pattern: "/security/secret-manager/create", component: CreateSecret },
    { pattern: "/security/secret-manager/secret/:name", component: SecretDetail },
  ],
};
