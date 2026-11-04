/* The 24 Compute Engine nav items that are genuinely out of scope for Vyomi (Bare Metal
 * Solution, sole-tenant nodes, TPUs, VM Manager, …): title + an honest "Not simulated in
 * Vyomi" panel, same pattern as gcp/storage's GAPS. No whole-page honest_page flag in
 * spec-map — these pages just never render anything inside the panel's data-vyomi-gap-box. */
import { Box, Typography } from "@mui/material";
import SecurityOutlinedIcon from "@mui/icons-material/esm/SecurityOutlined.js";
import RecommendOutlinedIcon from "@mui/icons-material/esm/RecommendOutlined.js";
import DnsOutlinedIcon from "@mui/icons-material/esm/DnsOutlined.js";
import DeveloperBoardOutlinedIcon from "@mui/icons-material/esm/DeveloperBoardOutlined.js";
import SellOutlinedIcon from "@mui/icons-material/esm/SellOutlined.js";
import EventAvailableOutlinedIcon from "@mui/icons-material/esm/EventAvailableOutlined.js";
import TrendingUpOutlinedIcon from "@mui/icons-material/esm/TrendingUpOutlined.js";
import SyncAltOutlinedIcon from "@mui/icons-material/esm/SyncAltOutlined.js";
import StorageOutlinedIcon from "@mui/icons-material/esm/StorageOutlined.js";
import CompareArrowsOutlinedIcon from "@mui/icons-material/esm/CompareArrowsOutlined.js";
import LayersOutlinedIcon from "@mui/icons-material/esm/LayersOutlined.js";
import ExtensionOutlinedIcon from "@mui/icons-material/esm/ExtensionOutlined.js";
import BuildOutlinedIcon from "@mui/icons-material/esm/BuildOutlined.js";
import RuleOutlinedIcon from "@mui/icons-material/esm/RuleOutlined.js";
import LanOutlinedIcon from "@mui/icons-material/esm/LanOutlined.js";
import AccountTreeOutlinedIcon from "@mui/icons-material/esm/AccountTreeOutlined.js";
import FolderSharedOutlinedIcon from "@mui/icons-material/esm/FolderSharedOutlined.js";
import ShoppingCartOutlinedIcon from "@mui/icons-material/esm/ShoppingCartOutlined.js";
import BuildCircleOutlinedIcon from "@mui/icons-material/esm/BuildCircleOutlined.js";
import RocketLaunchOutlinedIcon from "@mui/icons-material/esm/RocketLaunchOutlined.js";
import HubOutlinedIcon from "@mui/icons-material/esm/HubOutlined.js";
import ScienceOutlinedIcon from "@mui/icons-material/esm/ScienceOutlined.js";
import { NotSimulatedContainer } from "../../kit/common.jsx";

const ns = (title, feature) => function NotSimulatedPage() {
  return (
    <Box sx={{ pt: 2 }}>
      <Typography variant="h1" component="h1" sx={{ mb: 2 }}>{title}</Typography>
      <NotSimulatedContainer title={title} feature={feature || `Compute Engine ${title}`} />
    </Box>
  );
};

// [page id, title, route path (after "/compute/"), icon]
export const GAPS = [
  ["security-risk-overview", "Security risk overview", "security-risk-overview", SecurityOutlinedIcon],
  ["compute-advisor", "Compute Advisor", "compute-advisor", RecommendOutlinedIcon],
  ["sole-tenant-nodes", "Sole-tenant nodes", "sole-tenant-nodes", DnsOutlinedIcon],
  ["tpus", "TPUs", "tpus", DeveloperBoardOutlinedIcon],
  ["committed-use-discounts", "Committed use discounts", "committed-use-discounts", SellOutlinedIcon],
  ["reservations", "Reservations", "reservations", EventAvailableOutlinedIcon],
  ["capacity-advisor", "Capacity advisor", "capacity-advisor", TrendingUpOutlinedIcon],
  ["migrate-to-virtual-machines", "Migrate to Virtual Machines", "migrate-to-vms", SyncAltOutlinedIcon],
  ["storage-pools", "Storage Pools", "storage-pools", StorageOutlinedIcon],
  ["async-replication", "Async Replication", "async-replication", CompareArrowsOutlinedIcon],
  ["consistency-groups", "Consistency Groups", "consistency-groups", LayersOutlinedIcon],
  ["vm-extension-policies", "VM extension policies", "vm-extension-policies", ExtensionOutlinedIcon],
  ["patch", "Patch", "patch", BuildOutlinedIcon],
  ["os-policies", "OS policies", "os-policies", RuleOutlinedIcon],
  ["bms-servers", "Servers", "bms/servers", DnsOutlinedIcon],
  ["bms-networks", "Networks", "bms/networks", LanOutlinedIcon],
  ["bms-vrfs", "VRFs", "bms/vrfs", AccountTreeOutlinedIcon],
  ["bms-volumes", "Volumes", "bms/volumes", StorageOutlinedIcon],
  ["bms-nfs-shares", "NFS Shares", "bms/nfs-shares", FolderSharedOutlinedIcon],
  ["bms-procurements", "Procurements", "bms/procurements", ShoppingCartOutlinedIcon],
  ["bms-maintenance-events", "Maintenance Events", "bms/maintenance-events", BuildCircleOutlinedIcon],
  ["rollouts", "Rollouts", "rollouts", RocketLaunchOutlinedIcon],
  ["network-endpoint-groups", "Network endpoint groups", "network-endpoint-groups", HubOutlinedIcon],
  ["preview-features", "Preview Features", "preview-features", ScienceOutlinedIcon],
];

export const gapRoutes = () => GAPS.map(([, title, path]) => ({ pattern: `/compute/${path}`, component: ns(title) }));
export const gapById = (id) => GAPS.find((g) => g[0] === id);
export const gapLink = (id) => { const g = gapById(id); return g && { text: g[1], href: `#/compute/${g[2]}`, icon: g[3] }; };
