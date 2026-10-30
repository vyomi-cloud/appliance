import Home from "./Home.jsx";
import Stacks from "./Stacks.jsx";
import StackDetail from "./StackDetail.jsx";
import CreateStack from "./CreateStack.jsx";
import UpdateStack from "./UpdateStack.jsx";
import StackRefactors from "./StackRefactors.jsx";
import StackSets from "./StackSets.jsx";
import Exports from "./Exports.jsx";
import IacGenerator from "./IacGenerator.jsx";
import TemplateStudio from "./TemplateStudio.jsx";
import ActivatedExtensions, { ExtensionDetail } from "./ActivatedExtensions.jsx";
import { HooksOverview, InvocationSummary, Hooks, PublicExtensions, Publisher, Spotlight } from "./HonestPages.jsx";

export default {
  nav: [
    { type: "link", text: "Stacks", href: "#/cloudformation/stacks" },
    { type: "link", text: "Stack refactors", href: "#/cloudformation/stack-refactors" },
    { type: "link", text: "StackSets", href: "#/cloudformation/stacksets" },
    { type: "link", text: "Exports", href: "#/cloudformation/exports" },
    { type: "link", text: "IaC generator", href: "#/cloudformation/iac-generator" },
    { type: "link", text: "Template studio", href: "#/cloudformation/template-studio" },
    { type: "link", text: "Hooks overview", href: "#/cloudformation/hooks/overview" },
    { type: "link", text: "Invocation summary", href: "#/cloudformation/hooks/invocations" },
    { type: "link", text: "Hooks", href: "#/cloudformation/hooks/list" },
    { type: "section", text: "Registry", items: [
      { type: "link", text: "Public extensions", href: "#/cloudformation/registry/public-extensions" },
      { type: "link", text: "Activated extensions", href: "#/cloudformation/registry/activated-extensions" },
      { type: "link", text: "Publisher", href: "#/cloudformation/registry/publisher" },
    ] },
    { type: "link", text: "Spotlight", href: "#/cloudformation/spotlight" },
  ],
  routes: [
    { pattern: "/cloudformation", component: Home },
    { pattern: "/cloudformation/stacks", component: Stacks, crumbs: () => [{ text: "Stacks", href: "#/cloudformation/stacks" }] },
    { pattern: "/cloudformation/create", component: CreateStack, crumbs: () => [{ text: "Stacks", href: "#/cloudformation/stacks" }, { text: "Create stack", href: "#/cloudformation/create" }] },
    { pattern: "/cloudformation/stacks/:name", component: StackDetail, crumbs: (p) => [{ text: "Stacks", href: "#/cloudformation/stacks" }, { text: p.name, href: `#/cloudformation/stacks/${p.name}` }] },
    { pattern: "/cloudformation/stacks/:name/update", component: UpdateStack, crumbs: (p) => [{ text: "Stacks", href: "#/cloudformation/stacks" }, { text: p.name, href: `#/cloudformation/stacks/${p.name}` }, { text: "Update stack", href: `#/cloudformation/stacks/${p.name}/update` }] },
    { pattern: "/cloudformation/stack-refactors", component: StackRefactors, crumbs: () => [{ text: "Stack refactors", href: "#/cloudformation/stack-refactors" }] },
    { pattern: "/cloudformation/stacksets", component: StackSets, crumbs: () => [{ text: "StackSets", href: "#/cloudformation/stacksets" }] },
    { pattern: "/cloudformation/exports", component: Exports, crumbs: () => [{ text: "Exports", href: "#/cloudformation/exports" }] },
    { pattern: "/cloudformation/iac-generator", component: IacGenerator, crumbs: () => [{ text: "IaC generator", href: "#/cloudformation/iac-generator" }] },
    { pattern: "/cloudformation/template-studio", component: TemplateStudio, crumbs: () => [{ text: "Template studio", href: "#/cloudformation/template-studio" }] },
    { pattern: "/cloudformation/hooks/overview", component: HooksOverview, crumbs: () => [{ text: "Hooks overview", href: "#/cloudformation/hooks/overview" }] },
    { pattern: "/cloudformation/hooks/invocations", component: InvocationSummary, crumbs: () => [{ text: "Invocation summary", href: "#/cloudformation/hooks/invocations" }] },
    { pattern: "/cloudformation/hooks/list", component: Hooks, crumbs: () => [{ text: "Hooks", href: "#/cloudformation/hooks/list" }] },
    { pattern: "/cloudformation/registry/public-extensions", component: PublicExtensions, crumbs: () => [{ text: "Registry: Public extensions", href: "#/cloudformation/registry/public-extensions" }] },
    { pattern: "/cloudformation/registry/public-extensions/resource-type/:name", component: ExtensionDetail, crumbs: (p) => [{ text: "Registry: Public extensions", href: "#/cloudformation/registry/public-extensions" }, { text: p.name, href: `#/cloudformation/registry/public-extensions/resource-type/${p.name}` }] },
    { pattern: "/cloudformation/registry/activated-extensions", component: ActivatedExtensions, crumbs: () => [{ text: "Registry: Activated extensions", href: "#/cloudformation/registry/activated-extensions" }] },
    { pattern: "/cloudformation/registry/publisher", component: Publisher, crumbs: () => [{ text: "Registry: Publisher", href: "#/cloudformation/registry/publisher" }] },
    { pattern: "/cloudformation/spotlight", component: Spotlight, crumbs: () => [{ text: "CloudFormation Spotlight", href: "#/cloudformation/spotlight" }] },
  ],
};
