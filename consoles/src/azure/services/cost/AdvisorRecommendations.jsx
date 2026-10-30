import { useEffect, useState } from "react";
import { Button, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, ToolbarButton } from "@fluentui/react-components";
import { ArrowClockwise20Regular, ArrowDownload20Regular } from "@fluentui/react-icons";
import CostShell from "./CostShell.jsx";
import { costQuery } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { downloadCsv, ErrorBar, Loading } from "../../kit/common.jsx";

const DOLLAR = (n) => `$${Number(n || 0).toFixed(2)}`;
const SUGGEST = (monthly) => (monthly >= 20 ? "Consider right-sizing or shutting this resource down when idle."
  : monthly >= 1 ? "Review whether this resource's tier matches its real usage." : "Low spend — no action needed.");

export default function AdvisorRecommendations() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  const load = () => {
    setError(null); setRows(null);
    costQuery({ type: "ActualCost", timeframe: "MonthToDate", dataset: { grouping: [{ type: "Dimension", name: "ResourceId" }] } })
      .then((r) => setRows([...r.properties.rows].sort((a, b) => b[0] - a[0]))).catch(setError);
  };
  useEffect(load, []);

  return (
    <CostShell active="advisor">
      <div className="vy-page">
        <CapabilityContainer id="azure.cost.advisor_recommendations" title="Advisor recommendations" actions={
          <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
            <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={load}>Refresh</ToolbarButton>
            <ToolbarButton icon={<ArrowDownload20Regular />} disabled={!rows?.length}
              onClick={() => downloadCsv("recommendations.csv", [{ key: "name", label: "Resource" }, { key: "cost", label: "Monthly cost (USD)" }],
                (rows || []).map(([cost, name]) => ({ name, cost: cost.toFixed(2) })))}>Download as CSV</ToolbarButton>
          </div>
        }>
          <ErrorBar error={error} title="Failed to load recommendations" />
          {rows === null ? <Loading /> : !rows.length ? <p>No cost recommendations — your inventory has no billable resources yet.</p> : (
            <Table size="small" aria-label="Advisor recommendations">
              <TableHeader><TableRow><TableHeaderCell>Resource</TableHeaderCell><TableHeaderCell>Monthly cost (USD)</TableHeaderCell><TableHeaderCell>Recommendation</TableHeaderCell></TableRow></TableHeader>
              <TableBody>
                {rows.map(([cost, name]) => (
                  <TableRow key={name}><TableCell>{name}</TableCell><TableCell>{DOLLAR(cost)}</TableCell><TableCell>{SUGGEST(cost)}</TableCell></TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CapabilityContainer>
      </div>
    </CostShell>
  );
}
