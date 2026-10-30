import DashboardIcon from "@mui/icons-material/esm/Dashboard.js";
import ComputeIcon from "@mui/icons-material/esm/MemoryOutlined.js";
import DescriptionIcon from "@mui/icons-material/esm/DescriptionOutlined.js";
import StorageIcon from "@mui/icons-material/esm/StorageOutlined.js";
import GroupWorkIcon from "@mui/icons-material/esm/GroupWorkOutlined.js";
import ExtensionIcon from "@mui/icons-material/esm/ExtensionOutlined.js";
import BuildIcon from "@mui/icons-material/esm/BuildOutlined.js";
import DnsIcon from "@mui/icons-material/esm/DnsOutlined.js";
import SettingsIcon from "@mui/icons-material/esm/SettingsOutlined.js";
import OpenInNewIcon from "@mui/icons-material/esm/OpenInNew.js";
import { classicHref } from "../registry.js";

import Overview from "./Overview.jsx";
import VmInstances from "./VmInstances.jsx";
import CreateInstance from "./CreateInstance.jsx";
import InstanceDetail from "./InstanceDetail.jsx";
import InstanceTemplates from "./InstanceTemplates.jsx";
import MachineImages from "./MachineImages.jsx";
import Disks from "./Disks.jsx";
import CreateDisk from "./CreateDisk.jsx";
import Snapshots from "./Snapshots.jsx";
import Images from "./Images.jsx";
import InstanceGroups from "./InstanceGroups.jsx";
import HealthChecks from "./HealthChecks.jsx";
import Metadata from "./Metadata.jsx";
import Zones from "./Zones.jsx";
import Operations from "./Operations.jsx";
import Settings from "./Settings.jsx";
import { gapById, gapRoutes } from "./GapPages.jsx";

const link = (id, overrides) => { const g = gapById(id); return g ? { text: g[1], href: `#/compute/${g[2]}`, icon: g[3], ...overrides } : null; };

export default {
  nav: [
    { text: "Overview", href: "#/compute/overview", icon: DashboardIcon },
    link("security-risk-overview"),
    link("compute-advisor"),
    {
      section: "Virtual machines",
      items: [
        { text: "VM instances", href: "#/compute/instances", icon: ComputeIcon, match: ["#/compute/instances/create"] },
        { text: "Instance templates", href: "#/compute/instance-templates", icon: DescriptionIcon },
        link("sole-tenant-nodes"),
        { text: "Machine images", href: "#/compute/machine-images", icon: DescriptionIcon },
        link("tpus"),
        link("committed-use-discounts"),
        link("reservations"),
        link("capacity-advisor"),
        link("migrate-to-virtual-machines"),
      ].filter(Boolean),
    },
    {
      section: "Storage",
      items: [
        { text: "Disks", href: "#/compute/disks", icon: StorageIcon, match: ["#/compute/disks/create"] },
        link("storage-pools"),
        { text: "Snapshots", href: "#/compute/snapshots", icon: StorageIcon },
        { text: "Images", href: "#/compute/images", icon: StorageIcon },
        link("async-replication"),
        link("consistency-groups"),
      ].filter(Boolean),
    },
    {
      section: "Instance groups",
      items: [
        { text: "Instance groups", href: "#/compute/instance-groups", icon: GroupWorkIcon },
        { text: "Health checks", href: "#/compute/health-checks", icon: GroupWorkIcon },
      ],
    },
    { section: "VM Extension Manager", items: [link("vm-extension-policies")].filter(Boolean) },
    { section: "VM Manager", items: [link("patch"), link("os-policies")].filter(Boolean) },
    {
      section: "Bare Metal Solution",
      items: ["bms-servers", "bms-networks", "bms-vrfs", "bms-volumes", "bms-nfs-shares", "bms-procurements", "bms-maintenance-events"]
        .map((id) => link(id, { icon: DnsIcon })).filter(Boolean),
    },
    {
      section: "Settings",
      items: [
        link("rollouts"),
        { text: "Metadata", href: "#/compute/metadata", icon: SettingsIcon },
        { text: "Zones", href: "#/compute/zones", icon: SettingsIcon },
        link("network-endpoint-groups"),
        link("preview-features"),
        { text: "Operations", href: "#/compute/operations", icon: SettingsIcon },
        { text: "Settings", href: "#/compute/settings", icon: SettingsIcon },
      ].filter(Boolean),
    },
    { text: "Marketplace", href: classicHref("marketplace"), icon: OpenInNewIcon },
    { text: "Release Notes", href: classicHref("releasenotes"), icon: OpenInNewIcon },
  ],
  routes: [
    { pattern: "/compute", component: Overview },
    { pattern: "/compute/overview", component: Overview },
    { pattern: "/compute/instances", component: VmInstances },
    { pattern: "/compute/instances/create", component: CreateInstance },
    { pattern: "/compute/instances/:zone/:name", component: InstanceDetail },
    { pattern: "/compute/instance-templates", component: InstanceTemplates },
    { pattern: "/compute/machine-images", component: MachineImages },
    { pattern: "/compute/disks", component: Disks },
    { pattern: "/compute/disks/create", component: CreateDisk },
    { pattern: "/compute/snapshots", component: Snapshots },
    { pattern: "/compute/images", component: Images },
    { pattern: "/compute/instance-groups", component: InstanceGroups },
    { pattern: "/compute/health-checks", component: HealthChecks },
    { pattern: "/compute/metadata", component: Metadata },
    { pattern: "/compute/zones", component: Zones },
    { pattern: "/compute/operations", component: Operations },
    { pattern: "/compute/settings", component: Settings },
    ...gapRoutes(),
  ],
};
