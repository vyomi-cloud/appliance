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
import Storage from "./Storage.jsx";
import ObjectBrowser from "./ObjectBrowser.jsx";
import Applications from "./Applications.jsx";
import Config from "./Config.jsx";
import BackupForGke from "./BackupForGke.jsx";

// Marketplace / Release Notes: in the real console these are nav links OUT to a different
// Google product's own UI (Cloud Marketplace, the GKE release notes doc) — not part of this
// service's page set (ui-spec/gcp/kubernetes.json marks them `"external": true` with no
// `pages[]` entry), so there's nothing to simulate here.
const EXTERNAL_LINKS = [
  ["marketplace", "Marketplace", ShoppingCartIcon],
  ["release-notes", "Release Notes", DescriptionIcon],
];
const externalStub = (title) => function ExternalLinkPage() {
  return (
    <Box sx={{ pt: 2 }}>
      <Typography variant="h1" component="h1" sx={{ mb: 2 }}>{title}</Typography>
      <Typography variant="body2" color="text.secondary">In the real console, "{title}" opens a different Google Cloud product outside Kubernetes Engine.</Typography>
    </Box>
  );
};

export default {
  nav: [
    { text: "Overview", href: "#/kubernetes/overview", icon: DashboardIcon },
    { text: "Clusters", href: "#/kubernetes/clusters", icon: HubIcon, match: ["#/kubernetes/clusters/create"] },
    { text: "Workloads", href: "#/kubernetes/workloads", icon: ViewInArIcon },
    { text: "Applications", href: "#/kubernetes/applications", icon: AppsIcon },
    { text: "Secrets & ConfigMaps", href: "#/kubernetes/secrets-configmaps", icon: PasswordIcon },
    { text: "Storage", href: "#/kubernetes/storage", icon: StorageIcon },
    { text: "Object Browser", href: "#/kubernetes/object-browser", icon: FolderOutlinedIcon },
    { text: "Gateways, Services & Ingress", href: "#/kubernetes/discovery", icon: LanIcon },
    { text: "Backup for GKE", href: "#/kubernetes/backup", icon: BackupIcon },
    { text: "Config", href: "#/kubernetes/config", icon: SettingsIcon },
    { text: "Marketplace", href: "#/kubernetes/marketplace", icon: ShoppingCartIcon },
    { text: "Release Notes", href: "#/kubernetes/release-notes", icon: DescriptionIcon },
  ],
  routes: [
    { pattern: "/kubernetes", component: Overview },
    { pattern: "/kubernetes/overview", component: Overview },
    { pattern: "/kubernetes/clusters", component: Clusters },
    { pattern: "/kubernetes/clusters/create", component: CreateCluster },
    { pattern: "/kubernetes/clusters/:location/:name", component: ClusterDetail },
    { pattern: "/kubernetes/workloads", component: Workloads },
    { pattern: "/kubernetes/applications", component: Applications },
    { pattern: "/kubernetes/secrets-configmaps", component: SecretsConfigMaps },
    { pattern: "/kubernetes/storage", component: Storage },
    { pattern: "/kubernetes/object-browser", component: ObjectBrowser },
    { pattern: "/kubernetes/discovery", component: GatewaysServicesIngress },
    { pattern: "/kubernetes/backup", component: BackupForGke },
    { pattern: "/kubernetes/config", component: Config },
    ...EXTERNAL_LINKS.map(([p, t]) => ({ pattern: `/kubernetes/${p}`, component: externalStub(t) })),
  ],
};
