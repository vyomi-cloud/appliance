/* Cost Management's own left nav (the service IS the nav tree, unlike a per-resource blade). */
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Glyph } from "../../kit/common.jsx";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "changescope", label: "Change scope" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { group: "Reporting + analytics", items: [
    { id: "analysis", label: "Cost analysis" },
    { id: "exports", label: "Exports" },
  ] },
  { group: "Monitoring", items: [
    { id: "alerts", label: "Cost alerts" },
    { id: "alertrules", label: "Alert rules" },
    { id: "budgets", label: "Budgets" },
  ] },
  { group: "Optimization", items: [
    { id: "advisor", label: "Advisor recommendations" },
    { id: "reservations", label: "Reservations + Hybrid Benefit" },
    { id: "savingsplans", label: "Savings plans" },
  ] },
  { group: "Settings", items: [
    { id: "allocation", label: "Cost allocation" },
    { id: "configuration", label: "Configuration" },
    { id: "previewfeatures", label: "Preview features" },
  ] },
  { group: "Billing", items: [
    { id: "invoices", label: "Invoices" },
    { id: "paymentmethods", label: "Payment methods" },
    { id: "subscriptions", label: "Azure subscriptions" },
  ] },
  { group: "Help", items: [
    { id: "support", label: "New support request" },
  ] },
];

const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));

export default function CostShell({ active, children }) {
  return (
    <ResourceBlade title="Cost Management" subtitle={LABEL[active] && `| ${LABEL[active]}`} glyph={<Glyph id="cost" size={28} />}
      menu={MENU} active={active} hrefFor={(id) => `#/cost/${id}`}>
      {children}
    </ResourceBlade>
  );
}
