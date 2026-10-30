import Overview from "./Overview.jsx";
import ChangeScope from "./ChangeScope.jsx";
import CostAnalysis from "./CostAnalysis.jsx";
import Exports from "./Exports.jsx";
import CostAlerts from "./CostAlerts.jsx";
import AlertRules from "./AlertRules.jsx";
import Budgets from "./Budgets.jsx";
import CreateBudget from "./CreateBudget.jsx";
import AdvisorRecommendations from "./AdvisorRecommendations.jsx";
import SavingsPlans from "./SavingsPlans.jsx";
import PreviewFeatures from "./PreviewFeatures.jsx";
import Configuration from "./Configuration.jsx";
import AzureSubscriptions from "./AzureSubscriptions.jsx";
import { CostAllocation, DiagnoseAndSolveProblems, Invoices, NewSupportRequest, PaymentMethods, ReservationsHybridBenefit } from "./StaticPages.jsx";

const crumb = (text, href) => [{ text, href }];

export default {
  routes: [
    { pattern: "/cost", component: Overview },
    { pattern: "/cost/overview", component: Overview },
    { pattern: "/cost/changescope", component: ChangeScope, crumbs: () => crumb("Change scope", "#/cost/changescope") },
    { pattern: "/cost/diagnose", component: DiagnoseAndSolveProblems, crumbs: () => crumb("Diagnose and solve problems", "#/cost/diagnose") },
    { pattern: "/cost/analysis", component: CostAnalysis, crumbs: () => crumb("Cost analysis", "#/cost/analysis") },
    { pattern: "/cost/exports", component: Exports, crumbs: () => crumb("Exports", "#/cost/exports") },
    { pattern: "/cost/alerts", component: CostAlerts, crumbs: () => crumb("Cost alerts", "#/cost/alerts") },
    { pattern: "/cost/alertrules", component: AlertRules, crumbs: () => crumb("Alert rules", "#/cost/alertrules") },
    { pattern: "/cost/budgets", component: Budgets, crumbs: () => crumb("Budgets", "#/cost/budgets") },
    { pattern: "/cost/budgets/create", component: CreateBudget, crumbs: () => [{ text: "Budgets", href: "#/cost/budgets" }, { text: "Create budget", href: "#/cost/budgets/create" }] },
    { pattern: "/cost/advisor", component: AdvisorRecommendations, crumbs: () => crumb("Advisor recommendations", "#/cost/advisor") },
    { pattern: "/cost/reservations", component: ReservationsHybridBenefit, crumbs: () => crumb("Reservations + Hybrid Benefit", "#/cost/reservations") },
    { pattern: "/cost/savingsplans", component: SavingsPlans, crumbs: () => crumb("Savings plans", "#/cost/savingsplans") },
    { pattern: "/cost/allocation", component: CostAllocation, crumbs: () => crumb("Cost allocation", "#/cost/allocation") },
    { pattern: "/cost/configuration", component: Configuration, crumbs: () => crumb("Configuration", "#/cost/configuration") },
    { pattern: "/cost/previewfeatures", component: PreviewFeatures, crumbs: () => crumb("Preview features", "#/cost/previewfeatures") },
    { pattern: "/cost/invoices", component: Invoices, crumbs: () => crumb("Invoices", "#/cost/invoices") },
    { pattern: "/cost/paymentmethods", component: PaymentMethods, crumbs: () => crumb("Payment methods", "#/cost/paymentmethods") },
    { pattern: "/cost/subscriptions", component: AzureSubscriptions, crumbs: () => crumb("Azure subscriptions", "#/cost/subscriptions") },
    { pattern: "/cost/support", component: NewSupportRequest, crumbs: () => crumb("New support request", "#/cost/support") },
  ],
};
