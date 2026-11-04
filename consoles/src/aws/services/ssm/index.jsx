import Parameters from "./Parameters.jsx";
import CreateParameter from "./CreateParameter.jsx";
import ParameterDetail from "./ParameterDetail.jsx";
import Documents from "./Documents.jsx";
import CreateDocument from "./CreateDocument.jsx";
import DocumentDetail from "./DocumentDetail.jsx";
import Commands from "./Commands.jsx";
import RunCommand from "./RunCommand.jsx";
import CommandDetail from "./CommandDetail.jsx";
import Associations from "./Associations.jsx";
import CreateAssociation from "./CreateAssociation.jsx";
import AssociationDetail from "./AssociationDetail.jsx";
import MaintenanceWindows from "./MaintenanceWindows.jsx";
import CreateMaintenanceWindow from "./CreateMaintenanceWindow.jsx";
import MaintenanceWindowDetail from "./MaintenanceWindowDetail.jsx";
import PatchBaselines from "./PatchBaselines.jsx";
import CreatePatchBaseline from "./CreatePatchBaseline.jsx";
import PatchBaselineDetail from "./PatchBaselineDetail.jsx";

export default {
  nav: [
    { type: "link", text: "Parameter Store", href: "#/ssm/parameters" },
    { type: "link", text: "Documents", href: "#/ssm/documents" },
    { type: "section", text: "Run Command", items: [
      { type: "link", text: "Command history", href: "#/ssm/commands" },
      { type: "link", text: "Run command", href: "#/ssm/run-command" },
    ] },
    { type: "link", text: "State Manager", href: "#/ssm/associations" },
    { type: "link", text: "Maintenance Windows", href: "#/ssm/maintenance-windows" },
    { type: "link", text: "Patch Manager", href: "#/ssm/patch-baselines" },
  ],
  routes: [
    { pattern: "/ssm", component: Parameters, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Parameter Store", href: "#/ssm/parameters" }] },
    { pattern: "/ssm/parameters", component: Parameters, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Parameter Store", href: "#/ssm/parameters" }] },
    { pattern: "/ssm/create-parameter", component: CreateParameter, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Parameter Store", href: "#/ssm/parameters" }, { text: "Create parameter", href: "#/ssm/create-parameter" }] },
    { pattern: "/ssm/parameters/view", component: ParameterDetail, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Parameter Store", href: "#/ssm/parameters" }] },

    { pattern: "/ssm/documents", component: Documents, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Documents", href: "#/ssm/documents" }] },
    { pattern: "/ssm/create-document", component: CreateDocument, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Documents", href: "#/ssm/documents" }, { text: "Create document", href: "#/ssm/create-document" }] },
    { pattern: "/ssm/documents/view", component: DocumentDetail, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Documents", href: "#/ssm/documents" }] },

    { pattern: "/ssm/commands", component: Commands, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Command history", href: "#/ssm/commands" }] },
    { pattern: "/ssm/run-command", component: RunCommand, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Run a command", href: "#/ssm/run-command" }] },
    { pattern: "/ssm/commands/:id", component: CommandDetail, crumbs: (p) => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Command history", href: "#/ssm/commands" }, { text: p.id, href: `#/ssm/commands/${p.id}` }] },

    { pattern: "/ssm/associations", component: Associations, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "State Manager", href: "#/ssm/associations" }] },
    { pattern: "/ssm/create-association", component: CreateAssociation, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "State Manager", href: "#/ssm/associations" }, { text: "Create association", href: "#/ssm/create-association" }] },
    { pattern: "/ssm/associations/:id", component: AssociationDetail, crumbs: (p) => [{ text: "Systems Manager", href: "#/ssm" }, { text: "State Manager", href: "#/ssm/associations" }, { text: p.id, href: `#/ssm/associations/${p.id}` }] },

    { pattern: "/ssm/maintenance-windows", component: MaintenanceWindows, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Maintenance Windows", href: "#/ssm/maintenance-windows" }] },
    { pattern: "/ssm/create-maintenance-window", component: CreateMaintenanceWindow, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Maintenance Windows", href: "#/ssm/maintenance-windows" }, { text: "Create maintenance window", href: "#/ssm/create-maintenance-window" }] },
    { pattern: "/ssm/maintenance-windows/:id", component: MaintenanceWindowDetail, crumbs: (p) => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Maintenance Windows", href: "#/ssm/maintenance-windows" }, { text: p.id, href: `#/ssm/maintenance-windows/${p.id}` }] },

    { pattern: "/ssm/patch-baselines", component: PatchBaselines, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Patch Manager", href: "#/ssm/patch-baselines" }] },
    { pattern: "/ssm/create-patch-baseline", component: CreatePatchBaseline, crumbs: () => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Patch Manager", href: "#/ssm/patch-baselines" }, { text: "Create patch baseline", href: "#/ssm/create-patch-baseline" }] },
    { pattern: "/ssm/patch-baselines/:id", component: PatchBaselineDetail, crumbs: (p) => [{ text: "Systems Manager", href: "#/ssm" }, { text: "Patch Manager", href: "#/ssm/patch-baselines" }, { text: p.id, href: `#/ssm/patch-baselines/${p.id}` }] },
  ],
};
