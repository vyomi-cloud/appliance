import { Dashboard, Vaults, VaultDetail, Plans, CreatePlan, PlanDetail, Jobs, RestoreJobs, Protected } from "./Pages.jsx";

const root = { text: "AWS Backup", href: "#/backup" };
const c = (...xs) => () => [root, ...xs.map(([text, href]) => ({ text, href }))];
export default {
  nav: [
    { type: "link", text: "Dashboard", href: "#/backup" },
    { type: "section", text: "My account", items: [
      { type: "link", text: "Backup plans", href: "#/backup/plans" },
      { type: "link", text: "Backup vaults", href: "#/backup/vaults" },
      { type: "link", text: "Protected resources", href: "#/backup/protected-resources" },
      { type: "link", text: "Jobs", href: "#/backup/jobs" },
      { type: "link", text: "Restore jobs", href: "#/backup/restore-jobs" },
    ] },
  ],
  routes: [
    { pattern: "/backup", component: Dashboard, crumbs: c() },
    { pattern: "/backup/plans", component: Plans, crumbs: c(["Backup plans", "#/backup/plans"]) },
    { pattern: "/backup/create-plan", component: CreatePlan, crumbs: c(["Backup plans", "#/backup/plans"], ["Create backup plan", "#/backup/create-plan"]) },
    { pattern: "/backup/plans/view", component: PlanDetail, crumbs: c(["Backup plans", "#/backup/plans"]) },
    { pattern: "/backup/vaults", component: Vaults, crumbs: c(["Backup vaults", "#/backup/vaults"]) },
    { pattern: "/backup/vaults/view", component: VaultDetail, crumbs: c(["Backup vaults", "#/backup/vaults"]) },
    { pattern: "/backup/jobs", component: Jobs, crumbs: c(["Jobs", "#/backup/jobs"]) },
    { pattern: "/backup/restore-jobs", component: RestoreJobs, crumbs: c(["Restore jobs", "#/backup/restore-jobs"]) },
    { pattern: "/backup/protected-resources", component: Protected, crumbs: c(["Protected resources", "#/backup/protected-resources"]) },
  ],
};
