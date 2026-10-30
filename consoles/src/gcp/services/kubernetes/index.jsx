import { Box, Typography } from "@mui/material";
import DashboardIcon from "@mui/icons-material/esm/Dashboard.js";
import HubIcon from "@mui/icons-material/esm/Hub.js";
import ViewInArIcon from "@mui/icons-material/esm/ViewInAr.js";
import AppsIcon from "@mui/icons-material/esm/Apps.js";
import PasswordIcon from "@mui/icons-material/esm/Password.js";
import StorageIcon from "@mui/icons-material/esm/Storage.js";
import FolderOutlinedIcon from "@mui/icons-material/esm/FolderOutlined.js";
import LanIcon from "@mui/icons-material/esm/Lan.js";
import BackupIcon from "@mui/icons-material/esm/Backup.js";
import SettingsIcon from "@mui/icons-material/esm/Settings.js";
import ShoppingCartIcon from "@mui/icons-material/esm/ShoppingCartOutlined.js";
import DescriptionIcon from "@mui/icons-material/esm/DescriptionOutlined.js";
import Overview from "./Overview.jsx";
import Clusters from "./Clusters.jsx";
import CreateCluster from "./CreateCluster.jsx";
import ClusterDetail from "./ClusterDetail.jsx";
import Workloads from "./Workloads.jsx";
import SecretsConfigMaps from "./SecretsConfigMaps.jsx";
import GatewaysServicesIngress from "./GatewaysServicesIngress.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

const ns = (title, capId) => function NotSimulatedPage() {
  return (
    <Box sx={{ pt: 2 }}>
      <Typography variant="h1" component="h1" sx={{ mb: 2 }}>{title}</Typography>
      <CapabilityContainer id={capId} title={title} />
    </Box>
  );
};

const GAPS = [
  ["applications", "Applications", AppsIcon, "gcp.kubernetes.applications"],
  ["storage", "Storage", StorageIcon, "gcp.kubernetes.storage"],
  ["object-browser", "Object Browser", FolderOutlinedIcon, "gcp.kubernetes.object-browser"],
  ["backup", "Backup for GKE", BackupIcon, "gcp.kubernetes.backup"],
  ["config", "Config", SettingsIcon, "gcp.kubernetes.config"],
  ["marketplace", "Marketplace", ShoppingCartIcon, "gcp.kubernetes.config"],
  ["release-notes", "Release Notes", DescriptionIcon, "gcp.kubernetes.config"],
];
const gap = (id) => GAPS.find((g) => g[0] === id);
const link = (id) => { const [p, t, icon] = gap(id); return { text: t, href: `#/kubernetes/${p}`, icon }; };

export default {
  nav: [
    { text: "Overview", href: "#/kubernetes/overview", icon: DashboardIcon },
    { text: "Clusters", href: "#/kubernetes/clusters", icon: HubIcon, match: ["#/kubernetes/clusters/create"] },
    { text: "Workloads", href: "#/kubernetes/workloads", icon: ViewInArIcon },
    link("applications"),
    { text: "Secrets & ConfigMaps", href: "#/kubernetes/secrets-configmaps", icon: PasswordIcon },
    link("storage"),
    link("object-browser"),
    { text: "Gateways, Services & Ingress", href: "#/kubernetes/discovery", icon: LanIcon },
    link("backup"),
    link("config"),
    link("marketplace"),
    link("release-notes"),
  ],
  routes: [
    { pattern: "/kubernetes", component: Overview },
    { pattern: "/kubernetes/overview", component: Overview },
    { pattern: "/kubernetes/clusters", component: Clusters },
    { pattern: "/kubernetes/clusters/create", component: CreateCluster },
    { pattern: "/kubernetes/clusters/:location/:name", component: ClusterDetail },
    { pattern: "/kubernetes/workloads", component: Workloads },
    { pattern: "/kubernetes/secrets-configmaps", component: SecretsConfigMaps },
    { pattern: "/kubernetes/discovery", component: GatewaysServicesIngress },
    ...GAPS.map(([p, t, , capId]) => ({ pattern: `/kubernetes/${p}`, component: ns(t, capId) })),
  ],
};
