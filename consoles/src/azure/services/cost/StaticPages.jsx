/* Small Cost Management pages that are either pure navigation/informational content
 * (no backend claim to make) or a genuine capability gap (a real financial/billing
 * operation a simulator cannot perform) — grouped here to avoid one tiny file per page. */
import { useEffect, useState } from "react";
import CostShell from "./CostShell.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { listResourceGroups } from "../../kit/arm.js";

export function DiagnoseAndSolveProblems() {
  return (
    <CostShell active="diagnose">
      <div className="vy-page">
        <section className="vy-form-section">
          <h3>Diagnose and solve problems</h3>
          <p>Common cost-management problems and where to look:</p>
          <ul>
            <li><a href="#/cost/analysis">My costs don't match what I expect</a> — open Cost analysis and group by resource group or service.</li>
            <li><a href="#/cost/budgets">I want to be notified before I overspend</a> — create a Budget with alert conditions.</li>
            <li><a href="#/cost/alerts">I'm not seeing alerts I expect</a> — check Cost alerts; alerts fire once a budget crosses its threshold.</li>
            <li><a href="#/cost/changescope">I'm looking at the wrong subscription</a> — use Change scope.</li>
          </ul>
        </section>
      </div>
    </CostShell>
  );
}

export function ReservationsHybridBenefit() {
  const [rgs, setRgs] = useState(null);
  useEffect(() => { listResourceGroups().then(setRgs).catch(() => setRgs([])); }, []);
  return (
    <CostShell active="reservations">
      <div className="vy-page">
        <section className="vy-form-section">
          <h3>Reservations + Hybrid Benefit</h3>
          <p>{rgs === null ? "Loading your inventory..." : `Your subscription has ${rgs.length} resource group${rgs.length === 1 ? "" : "s"} that could benefit from a reservation or Azure Hybrid Benefit.`}</p>
        </section>
        <CapabilityContainer id="azure.cost.reservations_hybrid_benefit" title="Purchase a reservation" />
      </div>
    </CostShell>
  );
}

export function CostAllocation() {
  return (
    <CostShell active="allocation">
      <div className="vy-page">
        <CapabilityContainer id="azure.cost.cost_allocation" title="Cost allocation" />
      </div>
    </CostShell>
  );
}

export function Invoices() {
  return (
    <CostShell active="invoices">
      <div className="vy-page">
        <CapabilityContainer id="azure.cost.invoices" title="Invoices" />
      </div>
    </CostShell>
  );
}

export function PaymentMethods() {
  return (
    <CostShell active="paymentmethods">
      <div className="vy-page">
        <CapabilityContainer id="azure.cost.payment_methods" title="Payment methods" />
      </div>
    </CostShell>
  );
}

export function NewSupportRequest() {
  return (
    <CostShell active="support">
      <div className="vy-page">
        <CapabilityContainer id="azure.cost.new_support_request" title="New support request" />
      </div>
    </CostShell>
  );
}
