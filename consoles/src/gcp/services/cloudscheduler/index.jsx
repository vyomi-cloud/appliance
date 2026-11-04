import ScheduleIcon from "@mui/icons-material/esm/ScheduleOutlined.js";
import Jobs from "./Jobs.jsx";
import CreateJob from "./CreateJob.jsx";
import JobDetail from "./JobDetail.jsx";
import EditJob from "./EditJob.jsx";

export default {
  nav: [
    { text: "Jobs", href: "#/cloudscheduler", icon: ScheduleIcon, match: ["#/cloudscheduler/jobs"] },
  ],
  routes: [
    { pattern: "/cloudscheduler", component: Jobs },
    { pattern: "/cloudscheduler/jobs", component: Jobs },
    { pattern: "/cloudscheduler/jobs/new", component: CreateJob },
    { pattern: "/cloudscheduler/jobs/:region/:name", component: JobDetail },
    { pattern: "/cloudscheduler/jobs/:region/:name/edit", component: EditJob },
  ],
};
