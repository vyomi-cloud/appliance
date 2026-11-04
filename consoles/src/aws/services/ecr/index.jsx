import { Registry, RepositoryDetail, Repositories } from "./Pages.jsx";

const c = (...xs) => () => [...xs.map(([text, href]) => ({ text, href }))];
export default {
  nav: [
    { type: "section", text: "Private registry", items: [
      { type: "link", text: "Repositories", href: "#/ecr/repositories" },
      { type: "link", text: "Registry settings", href: "#/ecr/registry" },
    ] },
  ],
  routes: [
    { pattern: "/ecr", component: Repositories, crumbs: c(["Repositories", "#/ecr/repositories"]) },
    { pattern: "/ecr/repositories", component: Repositories, crumbs: c(["Repositories", "#/ecr/repositories"]) },
    { pattern: "/ecr/repositories/view", component: RepositoryDetail, crumbs: c(["Repositories", "#/ecr/repositories"]) },
    { pattern: "/ecr/registry", component: Registry, crumbs: c(["Registry settings", "#/ecr/registry"]) },
  ],
};
