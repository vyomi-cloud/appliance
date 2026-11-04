import { Box, Typography } from "@mui/material";
import LanOutlinedIcon from "@mui/icons-material/esm/LanOutlined.js";
import PublicOutlinedIcon from "@mui/icons-material/esm/PublicOutlined.js";
import SettingsEthernetIcon from "@mui/icons-material/esm/SettingsEthernet.js";
import VpnLockIcon from "@mui/icons-material/esm/VpnLock.js";
import SecurityIcon from "@mui/icons-material/esm/SecurityOutlined.js";
import AltRouteIcon from "@mui/icons-material/esm/AltRoute.js";
import HubIcon from "@mui/icons-material/esm/HubOutlined.js";
import ShareIcon from "@mui/icons-material/esm/ShareOutlined.js";
import CloudQueueIcon from "@mui/icons-material/esm/CloudQueueOutlined.js";
import ContentCopyIcon from "@mui/icons-material/esm/ContentCopyOutlined.js";
import ArticleIcon from "@mui/icons-material/esm/ArticleOutlined.js";
import VpcNetworks from "./VpcNetworks.jsx";
import CreateVpcNetwork from "./CreateVpcNetwork.jsx";
import VpcNetworkDetail from "./VpcNetworkDetail.jsx";
import Firewall from "./Firewall.jsx";
import CreateFirewallRule from "./CreateFirewallRule.jsx";
import IpAddresses from "./IpAddresses.jsx";
import ReserveAddress from "./ReserveAddress.jsx";
import Routes from "./Routes.jsx";
import CreateRoute from "./CreateRoute.jsx";
import VpcFlowLogs from "./VpcFlowLogs.jsx";
import ConnectivityTests from "./ConnectivityTests.jsx";
import CreateConnectivityTest from "./CreateConnectivityTest.jsx";
import ConnectivityTestDetail from "./ConnectivityTestDetail.jsx";
import InternalRanges from "./InternalRanges.jsx";
import SharedVpc from "./SharedVpc.jsx";
import ServerlessVpcAccess from "./ServerlessVpcAccess.jsx";
import PacketMirroring from "./PacketMirroring.jsx";
import NetworkCheckIcon from "@mui/icons-material/esm/NetworkCheckOutlined.js";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

const ns = (title, capId) => function NotSimulatedPage() {
  return (
    <Box sx={{ pt: 2 }}>
      <Typography variant="h1" component="h1" sx={{ mb: 2 }}>{title}</Typography>
      {capId ? <CapabilityContainer id={capId} title={title} /> : <NotSimulatedContainer title={title} feature={`VPC ${title}`} />}
    </Box>
  );
};

// Still-honest gaps: no backend can reasonably model these (real BGP/RPKI for BYOIP, real
// on-prem circuits for hybrid connectivity to on-premises/other clouds).
const GAPS = [
  ["bring-your-own-ip", "Bring your own IP", VpnLockIcon, "gcp.networking.byoip"],
  ["vpc-connectivity", "VPC connectivity", HubIcon, "gcp.networking.hybrid-connectivity"],
];
const gap = (id) => GAPS.find((g) => g[0] === id);
const link = (id) => { const [p, t, icon] = gap(id); return { text: t, href: `#/networking/${p}`, icon }; };

export default {
  nav: [
    { text: "VPC networks", href: "#/networking/networks/list", icon: LanOutlinedIcon, match: ["#/networking/networks/add", "#/networking/networks/details"] },
    { text: "IP addresses", href: "#/networking/addresses/list", icon: PublicOutlinedIcon, match: ["#/networking/addresses/add"] },
    { text: "Internal ranges", href: "#/networking/internal-ranges", icon: ContentCopyIcon },
    link("bring-your-own-ip"),
    { text: "Firewall", href: "#/networking/firewall", icon: SecurityIcon, match: ["#/networking/firewall/add"] },
    { text: "Routes", href: "#/networking/routes/list", icon: AltRouteIcon, match: ["#/networking/routes/add"] },
    link("vpc-connectivity"),
    { text: "Shared VPC", href: "#/networking/shared-vpc", icon: ShareIcon },
    { text: "Serverless VPC access", href: "#/networking/serverless-vpc-access", icon: CloudQueueIcon },
    { text: "Packet mirroring", href: "#/networking/packet-mirroring", icon: ArticleIcon },
    { text: "VPC Flow Logs", href: "#/networking/vpc-flow-logs", icon: SettingsEthernetIcon },
    { text: "Connectivity Tests", href: "#/networking/connectivity-tests/list", icon: NetworkCheckIcon, match: ["#/networking/connectivity-tests/add", "#/networking/connectivity-tests/details"] },
  ],
  routes: [
    { pattern: "/networking", component: VpcNetworks },
    { pattern: "/networking/networks/list", component: VpcNetworks },
    { pattern: "/networking/networks/add", component: CreateVpcNetwork },
    { pattern: "/networking/networks/details/:name", component: VpcNetworkDetail },
    { pattern: "/networking/firewall", component: Firewall },
    { pattern: "/networking/firewall/add", component: CreateFirewallRule },
    { pattern: "/networking/addresses/list", component: IpAddresses },
    { pattern: "/networking/addresses/add", component: ReserveAddress },
    { pattern: "/networking/routes/list", component: Routes },
    { pattern: "/networking/routes/add", component: CreateRoute },
    { pattern: "/networking/internal-ranges", component: InternalRanges },
    { pattern: "/networking/shared-vpc", component: SharedVpc },
    { pattern: "/networking/serverless-vpc-access", component: ServerlessVpcAccess },
    { pattern: "/networking/packet-mirroring", component: PacketMirroring },
    { pattern: "/networking/vpc-flow-logs", component: VpcFlowLogs },
    { pattern: "/networking/connectivity-tests/list", component: ConnectivityTests },
    { pattern: "/networking/connectivity-tests/add", component: CreateConnectivityTest },
    { pattern: "/networking/connectivity-tests/details/:name", component: ConnectivityTestDetail },
    ...GAPS.map(([p, t, , capId]) => ({ pattern: `/networking/${p}`, component: ns(t, capId) })),
  ],
};
