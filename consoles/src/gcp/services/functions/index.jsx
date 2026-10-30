import DashboardIcon from "@mui/icons-material/esm/Dashboard.js";
import FunctionsIcon from "@mui/icons-material/esm/FunctionsOutlined.js";
import WorkIcon from "@mui/icons-material/esm/WorkOutline.js";
import DnsIcon from "@mui/icons-material/esm/Dns.js";
import PublicIcon from "@mui/icons-material/esm/Public.js";
import DescriptionIcon from "@mui/icons-material/esm/DescriptionOutlined.js";
import OpenInNewIcon from "@mui/icons-material/esm/OpenInNew.js";
import Overview from "./Overview.jsx";
import Services from "./Services.jsx";
import CreateService from "./CreateService.jsx";
import ServiceDetail from "./ServiceDetail.jsx";
import Jobs from "./Jobs.jsx";
import WorkerPools from "./WorkerPools.jsx";
import DomainMappings from "./DomainMappings.jsx";

export default {
  nav: [
    { text: "Overview", href: "#/functions/overview", icon: DashboardIcon },
    { text: "Services", href: "#/functions/services", icon: FunctionsIcon, match: ["#/functions/create", "#/functions/detail"] },
    { text: "Jobs", href: "#/functions/jobs", icon: WorkIcon },
    { text: "Worker pools", href: "#/functions/worker-pools", icon: DnsIcon },
    { text: "Domain mappings", href: "#/functions/domain-mappings", icon: PublicIcon },
    { text: "Release Notes", href: "https://cloud.google.com/run/docs/release-notes", icon: DescriptionIcon, external: true, endIcon: OpenInNewIcon },
  ],
  routes: [
    { pattern: "/functions", component: Services },
    { pattern: "/functions/overview", component: Overview },
    { pattern: "/functions/services", component: Services },
    { pattern: "/functions/create", component: CreateService },
    { pattern: "/functions/detail/:region/:name", component: ServiceDetail },
    { pattern: "/functions/jobs", component: Jobs },
    { pattern: "/functions/worker-pools", component: WorkerPools },
    { pattern: "/functions/domain-mappings", component: DomainMappings },
  ],
};
