import { useEffect, useState } from "react";
import { Button, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular } from "@fluentui/react-icons";
import CostShell from "./CostShell.jsx";
import { dismissAlert, listAlerts, reactivateAlert } from "./api.js";
import { ErrorBar, Loading, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

export default function CostAlerts() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const [sel, setSel] = useState(new Set());

  const load = () => { setError(null); listAlerts().then(setItems).catch(setError); };
  useEffect(load, []);

  if (items === null) return <CostShell active="alerts"><Loading /></CostShell>;
  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  return (
    <CostShell active="alerts">
      <div className="vy-page">
        <CapabilityContainer id="azure.cost.cost_alerts" title="Cost alerts" actions={
          <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
            <ToolbarButton icon={<Add20Regular />} as="a" href="#/cost/budgets/create">Add</ToolbarButton>
            <ToolbarButton as="a" href="#/cost/alertrules">Alert rules</ToolbarButton>
            <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={load}>Refresh</ToolbarButton>
            <ToolbarButton disabled={!sel.size} onClick={async () => { await Promise.all([...sel].map((n) => dismissAlert(n))); setSel(new Set()); load(); }}>Dismiss</ToolbarButton>
            <ToolbarButton disabled={!sel.size} onClick={async () => { await Promise.all([...sel].map((n) => reactivateAlert(n))); setSel(new Set()); load(); }}>Re-Activate</ToolbarButton>
          </div>
        }>
          <ErrorBar error={error} title="Failed to load alerts" />
          {!items.length ? <p>No cost alerts to display. Alerts appear automatically once a budget crosses its threshold.</p> : (
            <Table size="small" aria-label="Cost alerts">
              <TableHeader><TableRow><TableHeaderCell /><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell><TableHeaderCell>Scope</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell><TableHeaderCell>Created on</TableHeaderCell></TableRow></TableHeader>
              <TableBody>
                {items.map((a) => (
                  <TableRow key={a.name}>
                    <TableCell><input type="checkbox" checked={sel.has(a.name)} onChange={() => toggle(a.name)} aria-label={`Select ${a.name}`} /></TableCell>
                    <TableCell>{a.properties.description}</TableCell>
                    <TableCell>{a.properties.definition.type}</TableCell>
                    <TableCell>{a.properties.details.scope}</TableCell>
                    <TableCell>{a.properties.status}</TableCell>
                    <TableCell>{fmtDate(a.properties.creationTime)}</TableCell>
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
