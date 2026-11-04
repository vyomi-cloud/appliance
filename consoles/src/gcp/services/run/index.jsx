import DashboardIcon from "@mui/icons-material/esm/Dashboard.js";
import RunIcon from "@mui/icons-material/esm/DirectionsRunOutlined.js";
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
import CreateJob from "./CreateJob.jsx";
import JobDetail from "./JobDetail.jsx";
import WorkerPools from "./WorkerPools.jsx";
import DomainMappings from "./DomainMappings.jsx";

export default {
  nav: [
    { text: "Overview", href: "#/run/overview", icon: DashboardIcon },
    { text: "Services", href: "#/run/services", icon: RunIcon, match: ["#/run/create", "#/run/detail"] },
    { text: "Jobs", href: "#/run/jobs", icon: WorkIcon, match: ["#/run/jobs/create", "#/run/jobs/details"] },
    { text: "Worker pools", href: "#/run/worker-pools", icon: DnsIcon },
    { text: "Domain mappings", href: "#/run/domains", icon: PublicIcon },
    { text: "Release Notes", href: "https://cloud.google.com/run/docs/release-notes", icon: DescriptionIcon, external: true, endIcon: OpenInNewIcon },
  ],
  routes: [
    { pattern: "/run", component: Services },
    { pattern: "/run/overview", component: Overview },
    { pattern: "/run/services", component: Services },
    { pattern: "/run/create", component: CreateService },
    { pattern: "/run/detail/:region/:name", component: ServiceDetail },
    { pattern: "/run/jobs", component: Jobs },
    { pattern: "/run/jobs/create", component: CreateJob },
    { pattern: "/run/jobs/details/:region/:name", component: JobDetail },
    { pattern: "/run/worker-pools", component: WorkerPools },
    { pattern: "/run/domains", component: DomainMappings },
  ],
};
