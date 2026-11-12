import AccountTreeIcon from "@mui/icons-material/esm/AccountTreeOutlined.js";
import ManageResources from "./ManageResources.jsx";
import CreateProject from "./CreateProject.jsx";

export default {
  nav: [
    { text: "Manage resources", href: "#/resource-manager", icon: AccountTreeIcon },
  ],
  routes: [
    { pattern: "/resource-manager", component: ManageResources },
    { pattern: "/resource-manager/create", component: CreateProject },
  ],
};
