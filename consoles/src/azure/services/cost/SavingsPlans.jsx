import { Table, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import CostShell from "./CostShell.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";

export default function SavingsPlans() {
  return (
    <CostShell active="savingsplans">
      <div className="vy-page">
        <section className="vy-form-section">
          <h3>Savings plans</h3>
          <Table size="small" aria-label="Savings plans">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell><TableHeaderCell>Term</TableHeaderCell>
                <TableHeaderCell>Benefit scope</TableHeaderCell><TableHeaderCell>Utilization</TableHeaderCell><TableHeaderCell>Renewal</TableHeaderCell>
              </TableRow>
            </TableHeader>
          </Table>
          <p style={{ margin: "12px 0" }}>No savings plans to display.</p>
        </section>
        <NotSimulatedContainer title="Purchase a savings plan" feature="Purchasing a savings plan"
          note="Committing to a real-money hourly spend plan against a payment method is out of scope for a simulator." />
      </div>
    </CostShell>
  );
}
