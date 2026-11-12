import BackupIcon from "@mui/icons-material/esm/BackupOutlined.js";
import BackupDr from "./BackupDr.jsx";

export default {
  nav: [{ text: "Backup and DR", href: "#/backupdr", icon: BackupIcon, match: ["#/backupdr"] }],
  routes: [{ pattern: "/backupdr", component: BackupDr }],
};
