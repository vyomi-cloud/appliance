import PlayCircleIcon from "@mui/icons-material/esm/PlayCircleOutline.js";
import StorageIcon from "@mui/icons-material/esm/Storage.js";
import BackupIcon from "@mui/icons-material/esm/Backup.js";
import Instances from "./Instances.jsx";
import GetStarted from "./GetStarted.jsx";
import ChooseEngine from "./ChooseEngine.jsx";
import CreateInstance from "./CreateInstance.jsx";
import Backups from "./Backups.jsx";
import InstanceOverview from "./InstanceOverview.jsx";
import Connections from "./Connections.jsx";
import Users from "./Users.jsx";
import AddUser from "./AddUser.jsx";
import Databases from "./Databases.jsx";
import CreateDatabase from "./CreateDatabase.jsx";
import InstanceBackups from "./InstanceBackups.jsx";
import Replicas from "./Replicas.jsx";
import Operations from "./Operations.jsx";
import SystemInsights from "./SystemInsights.jsx";
import QueryInsights from "./QueryInsights.jsx";
import CloudSqlStudio from "./CloudSqlStudio.jsx";

export default {
  nav: [
    { text: "Get Started", href: "#/sql/get-started", icon: PlayCircleIcon },
    { text: "Instances", href: "#/sql", icon: StorageIcon, match: ["#/sql/create", "#/sql/instances"] },
    { text: "Backups", href: "#/sql/backups", icon: BackupIcon },
  ],
  routes: [
    { pattern: "/sql", component: Instances },
    { pattern: "/sql/get-started", component: GetStarted },
    { pattern: "/sql/create", component: ChooseEngine },
    { pattern: "/sql/create/instance", component: CreateInstance },
    { pattern: "/sql/backups", component: Backups },
    { pattern: "/sql/instances/:name/overview", component: InstanceOverview },
    { pattern: "/sql/instances/:name/system-insights", component: SystemInsights },
    { pattern: "/sql/instances/:name/query-insights", component: QueryInsights },
    { pattern: "/sql/instances/:name/studio", component: CloudSqlStudio },
    { pattern: "/sql/instances/:name/connections", component: Connections },
    { pattern: "/sql/instances/:name/users", component: Users },
    { pattern: "/sql/instances/:name/users/add", component: AddUser },
    { pattern: "/sql/instances/:name/databases", component: Databases },
    { pattern: "/sql/instances/:name/databases/create", component: CreateDatabase },
    { pattern: "/sql/instances/:name/backups", component: InstanceBackups },
    { pattern: "/sql/instances/:name/replicas", component: Replicas },
    { pattern: "/sql/instances/:name/operations", component: Operations },
  ],
};
