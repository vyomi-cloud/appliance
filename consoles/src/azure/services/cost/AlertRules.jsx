import { useEffect, useState } from "react";
import { Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import CostShell from "./CostShell.jsx";
import { listBudgets } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";

export default function AlertRules() {
  const [budgets, setBudgets] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { listBudgets().then(setBudgets).catch(setError); }, []);

  const rules = (budgets || []).flatMap((b) => Object.entries(b.properties.notifications || {}).map(([key, n]) => ({
    key: `${b.name}/${key}`, budget: b.name, type: n.thresholdType || "Actual", threshold: n.threshold,
    emails: (n.contactEmails || []).length, enabled: n.enabled !== false,
  })));

  return (
    <CostShell active="alertrules">
      <div className="vy-page">
        <CapabilityContainer id="azure.cost.alert_rules" title="Alert rules">
          <ErrorBar error={error} title="Failed to load alert rules" />
          {budgets === null ? <Loading /> : !rules.length ? <p>No alert rules yet — alert conditions are set when you create a budget.</p> : (
            <Table size="small" aria-label="Alert rules">
              <TableHeader><TableRow><TableHeaderCell>Budget</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell><TableHeaderCell>Threshold</TableHeaderCell><TableHeaderCell>Recipients</TableHeaderCell><TableHeaderCell>Enabled</TableHeaderCell></TableRow></TableHeader>
              <TableBody>
                {rules.map((r) => (
                  <TableRow key={r.key}>
                    <TableCell><a href="#/cost/budgets">{r.budget}</a></TableCell>
                    <TableCell>{r.type}</TableCell>
                    <TableCell>{r.threshold}% of budget</TableCell>
                    <TableCell>{r.emails}</TableCell>
                    <TableCell>{r.enabled ? "Yes" : "No"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CapabilityContainer>
      </div>
    </CostShell>
  );
}
