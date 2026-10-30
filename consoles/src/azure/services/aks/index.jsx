import KubernetesServices from "./KubernetesServices.jsx";
import CreateKubernetesCluster from "./CreateKubernetesCluster.jsx";
import ClusterBlade, { MENU } from "./ClusterBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const cluster = (p) => ({ text: p.name, href: `#/aks/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/aks", component: KubernetesServices },
    { pattern: "/aks/create", component: CreateKubernetesCluster, crumbs: () => [{ text: "Create Kubernetes cluster", href: "#/aks/create" }] },
    { pattern: "/aks/:rg/:name", component: ClusterBlade, crumbs: (p) => [cluster(p)] },
    { pattern: "/aks/:rg/:name/:panel", component: ClusterBlade, crumbs: (p) => [cluster(p), { text: label[p.panel] || p.panel, href: `#/aks/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
