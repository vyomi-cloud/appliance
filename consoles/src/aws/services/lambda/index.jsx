import Dashboard from "./Dashboard.jsx";
import GetStarted from "./GetStarted.jsx";
import Functions from "./Functions.jsx";
import WebFunctions from "./WebFunctions.jsx";
import CreateFunction from "./CreateFunction.jsx";
import CreateWebFunction from "./CreateWebFunction.jsx";
import FunctionDetail from "./FunctionDetail.jsx";
import CreateAliasPage from "./CreateAliasPage.jsx";
import AddTriggerPage from "./AddTriggerPage.jsx";
import Layers from "./Layers.jsx";
import CreateLayer from "./CreateLayer.jsx";
import EventSourceMappings from "./EventSourceMappings.jsx";
import Extensions from "./Extensions.jsx";
import {
  Applications, CapacityProviders, CodeSigningConfigurations, CreateApplication, CreateCapacityProvider,
  CreateMicrovmImage, CreateNetworkConnector, MicrovmImages, Microvms, NetworkConnectors, Replicas,
  RunMicrovm, StepFunctionsStateMachines,
} from "./HonestPages.jsx";

export default {
  nav: [
    { type: "link", text: "Dashboard", href: "#/lambda/home" },
    { type: "link", text: "Applications", href: "#/lambda/applications" },
    { type: "link", text: "Event Functions", href: "#/lambda/functions" },
    { type: "link", text: "Web Functions", href: "#/lambda/web-functions" },
    { type: "section", text: "Event Function resources", items: [
      { type: "link", text: "Capacity providers", href: "#/lambda/capacity-providers" },
      { type: "link", text: "Code signing configurations", href: "#/lambda/code-signing-configurations" },
      { type: "link", text: "Event source mappings", href: "#/lambda/event-source-mappings" },
      { type: "link", text: "Layers", href: "#/lambda/layers" },
      { type: "link", text: "Replicas", href: "#/lambda/replicas" },
    ] },
    { type: "section", text: "MicroVMs", items: [
      { type: "link", text: "MicroVM Images", href: "#/lambda/microvm-images" },
      { type: "link", text: "MicroVMs", href: "#/lambda/microvms" },
    ] },
    { type: "link", text: "Network connectors", href: "#/lambda/network-connectors" },
    { type: "section", text: "Related AWS resources", items: [
      { type: "link", text: "Step Functions state machines", href: "#/lambda/statemachines" },
    ] },
    { type: "divider" },
    { type: "link", text: "Extensions", href: "#/lambda/extensions" },
  ],
  routes: [
    { pattern: "/lambda", component: Dashboard },
    { pattern: "/lambda/home", component: Dashboard, crumbs: () => [{ text: "Dashboard", href: "#/lambda/home" }] },
    { pattern: "/lambda/get-started", component: GetStarted, crumbs: () => [{ text: "AWS Lambda", href: "#/lambda/get-started" }] },
    { pattern: "/lambda/extensions", component: Extensions, crumbs: () => [{ text: "Extensions", href: "#/lambda/extensions" }] },

    { pattern: "/lambda/functions", component: Functions, crumbs: () => [{ text: "Event Functions", href: "#/lambda/functions" }] },
    { pattern: "/lambda/create/function", component: CreateFunction, crumbs: () => [{ text: "Event Functions", href: "#/lambda/functions" }, { text: "Create function", href: "#/lambda/create/function" }] },
    { pattern: "/lambda/functions/:name", component: FunctionDetail, crumbs: (p) => [{ text: "Functions", href: "#/lambda/functions" }, { text: p.name, href: `#/lambda/functions/${p.name}` }] },
    { pattern: "/lambda/functions/:name/create-alias", component: CreateAliasPage, crumbs: (p) => [{ text: "Functions", href: "#/lambda/functions" }, { text: p.name, href: `#/lambda/functions/${p.name}` }, { text: "Create alias", href: `#/lambda/functions/${p.name}/create-alias` }] },
    { pattern: "/lambda/functions/:name/add-trigger", component: AddTriggerPage, crumbs: (p) => [{ text: "Functions", href: "#/lambda/functions" }, { text: p.name, href: `#/lambda/functions/${p.name}` }, { text: "Add trigger", href: `#/lambda/functions/${p.name}/add-trigger` }] },

    { pattern: "/lambda/web-functions", component: WebFunctions, crumbs: () => [{ text: "Web Functions", href: "#/lambda/web-functions" }] },
    { pattern: "/lambda/create/web-function", component: CreateWebFunction, crumbs: () => [{ text: "Web Functions", href: "#/lambda/web-functions" }, { text: "Create Web Function", href: "#/lambda/create/web-function" }] },

    { pattern: "/lambda/layers", component: Layers, crumbs: () => [{ text: "Layers", href: "#/lambda/layers" }] },
    { pattern: "/lambda/create/layer", component: CreateLayer, crumbs: () => [{ text: "Layers", href: "#/lambda/layers" }, { text: "Create layer", href: "#/lambda/create/layer" }] },

    { pattern: "/lambda/event-source-mappings", component: EventSourceMappings, crumbs: () => [{ text: "Event source mappings", href: "#/lambda/event-source-mappings" }] },

    { pattern: "/lambda/applications", component: Applications, crumbs: () => [{ text: "Applications", href: "#/lambda/applications" }] },
    { pattern: "/lambda/create/application", component: CreateApplication, crumbs: () => [{ text: "Applications", href: "#/lambda/applications" }, { text: "Create application", href: "#/lambda/create/application" }] },
    { pattern: "/lambda/capacity-providers", component: CapacityProviders, crumbs: () => [{ text: "Capacity providers", href: "#/lambda/capacity-providers" }] },
    { pattern: "/lambda/create/capacity-provider", component: CreateCapacityProvider, crumbs: () => [{ text: "Capacity providers", href: "#/lambda/capacity-providers" }, { text: "Create capacity provider", href: "#/lambda/create/capacity-provider" }] },
    { pattern: "/lambda/code-signing-configurations", component: CodeSigningConfigurations, crumbs: () => [{ text: "Code signing configurations", href: "#/lambda/code-signing-configurations" }] },
    { pattern: "/lambda/replicas", component: Replicas, crumbs: () => [{ text: "Replicas", href: "#/lambda/replicas" }] },
    { pattern: "/lambda/microvm-images", component: MicrovmImages, crumbs: () => [{ text: "MicroVM Images", href: "#/lambda/microvm-images" }] },
    { pattern: "/lambda/create/microvm-image", component: CreateMicrovmImage, crumbs: () => [{ text: "MicroVM Images", href: "#/lambda/microvm-images" }, { text: "Create MicroVM Image", href: "#/lambda/create/microvm-image" }] },
    { pattern: "/lambda/microvms", component: Microvms, crumbs: () => [{ text: "MicroVMs", href: "#/lambda/microvms" }] },
    { pattern: "/lambda/create/microvm", component: RunMicrovm, crumbs: () => [{ text: "MicroVMs", href: "#/lambda/microvms" }, { text: "Run MicroVM", href: "#/lambda/create/microvm" }] },
    { pattern: "/lambda/network-connectors", component: NetworkConnectors, crumbs: () => [{ text: "Network connectors", href: "#/lambda/network-connectors" }] },
    { pattern: "/lambda/create/network-connector", component: CreateNetworkConnector, crumbs: () => [{ text: "Network connectors", href: "#/lambda/network-connectors" }, { text: "Create network connector", href: "#/lambda/create/network-connector" }] },
    { pattern: "/lambda/statemachines", component: StepFunctionsStateMachines, crumbs: () => [{ text: "Step Functions state machines", href: "#/lambda/statemachines" }] },
  ],
};
