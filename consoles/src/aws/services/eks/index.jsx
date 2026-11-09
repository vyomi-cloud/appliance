import { Clusters, CreateCluster, ClusterDetail } from "./Pages.jsx";

const root = { text: "Amazon EKS", href: "#/eks" };
const c = (...xs) => () => [root, ...xs.map(([text, href]) => ({ text, href }))];
export default {
  nav: [
    { type: "link", text: "Clusters", href: "#/eks/clusters" },
    { type: "divider" },
    { type: "link", text: "Create cluster", href: "#/eks/create" },
  ],
  routes: [
    { pattern: "/eks", component: Clusters, crumbs: c() },
    { pattern: "/eks/clusters", component: Clusters, crumbs: c(["Clusters", "#/eks/clusters"]) },
    { pattern: "/eks/create", component: CreateCluster, crumbs: c(["Clusters", "#/eks/clusters"], ["Create cluster", "#/eks/create"]) },
    { pattern: "/eks/clusters/view", component: ClusterDetail, crumbs: c(["Clusters", "#/eks/clusters"]) },
  ],
};
