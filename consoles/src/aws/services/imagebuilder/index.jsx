import { Components, ComponentDetail, Distributions, ImageDetail, Images, Infrastructure, PipelineDetail, Pipelines, RecipeDetail, Recipes } from "./Pages.jsx";

const c = (...xs) => () => xs.map(([text, href]) => ({ text, href }));
export default {
  nav: [
    { type: "link", text: "Image pipelines", href: "#/imagebuilder/pipelines" },
    { type: "link", text: "Images", href: "#/imagebuilder/images" },
    { type: "link", text: "Components", href: "#/imagebuilder/components" },
    { type: "link", text: "Image recipes", href: "#/imagebuilder/recipes" },
    { type: "link", text: "Infrastructure configurations", href: "#/imagebuilder/infrastructure" },
    { type: "link", text: "Distribution settings", href: "#/imagebuilder/distributions" },
  ],
  routes: [
    { pattern: "/imagebuilder", component: Pipelines, crumbs: c(["Image pipelines", "#/imagebuilder/pipelines"]) },
    { pattern: "/imagebuilder/pipelines", component: Pipelines, crumbs: c(["Image pipelines", "#/imagebuilder/pipelines"]) },
    { pattern: "/imagebuilder/pipelines/view", component: PipelineDetail, crumbs: c(["Image pipelines", "#/imagebuilder/pipelines"]) },
    { pattern: "/imagebuilder/images", component: Images, crumbs: c(["Images", "#/imagebuilder/images"]) },
    { pattern: "/imagebuilder/images/view", component: ImageDetail, crumbs: c(["Images", "#/imagebuilder/images"]) },
    { pattern: "/imagebuilder/components", component: Components, crumbs: c(["Components", "#/imagebuilder/components"]) },
    { pattern: "/imagebuilder/components/view", component: ComponentDetail, crumbs: c(["Components", "#/imagebuilder/components"]) },
    { pattern: "/imagebuilder/recipes", component: Recipes, crumbs: c(["Image recipes", "#/imagebuilder/recipes"]) },
    { pattern: "/imagebuilder/recipes/view", component: RecipeDetail, crumbs: c(["Image recipes", "#/imagebuilder/recipes"]) },
    { pattern: "/imagebuilder/infrastructure", component: Infrastructure, crumbs: c(["Infrastructure configurations", "#/imagebuilder/infrastructure"]) },
    { pattern: "/imagebuilder/distributions", component: Distributions, crumbs: c(["Distribution settings", "#/imagebuilder/distributions"]) },
  ],
};
