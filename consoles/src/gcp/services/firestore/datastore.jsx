import StorageIcon from "@mui/icons-material/esm/Storage.js";
import DatastoreStudio from "./DatastoreStudio.jsx";

export default {
  nav: [{ text: "Entities", href: "#/datastore", icon: StorageIcon }],
  routes: [{ pattern: "/datastore", component: DatastoreStudio }],
};
