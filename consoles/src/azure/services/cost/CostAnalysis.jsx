import { useEffect, useMemo, useState } from "react";
import { Button, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import CostShell from "./CostShell.jsx";
import { costQuery, listBudgets, toBudgetFilter } from "./api.js";
import { listResourceGroups } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading, ErrorBar } from "../../kit/common.jsx";
import { getPrefs } from "./prefs.js";

const DOLLAR = (n) => `$${Number(n || 0).toFixed(2)}`;
const GROUPINGS = { "Service name": "ServiceName", Location: "ResourceLocation", "Resource group name": "ResourceGroupName" };

function Breakdown({ title, dim }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    costQuery({ type: "ActualCost", timeframe: "MonthToDate", dataset: { grouping: [{ type: "Dimension", name: dim }] } })
      .then((r) => setRows(r.properties.rows)).catch(() => setRows([]));
  }, [dim]);
  return (
    <CapabilityContainer id="azure.cost.cost_analysis" title={title}>
      {rows === null ? <Loading /> : rows.length === 0 ? <p>No cost yet.</p> : (
        <Table size="small" aria-label={title}>
          <TableHeader><TableRow><TableHeaderCell>{title}</TableHeaderCell><TableHeaderCell>Cost</TableHeaderCell></TableRow></TableHeader>
          <TableBody>{rows.map(([cost, key]) => <TableRow key={key}><TableCell>{key}</TableCell><TableCell>{DOLLAR(cost)}</TableCell></TableRow>)}</TableBody>
        </Table>
      )}
    </CapabilityContainer>
  );
}

export default function CostAnalysis() {
  const [view, setView] = useState("Accumulated costs");
  const [granularity, setGranularity] = useState("Accumulated");
  const [groupBy, setGroupBy] = useState("None");
  const [rgFilter, setRgFilter] = useState("");
  const [rgs, setRgs] = useState([]);
  const [showFilter, setShowFilter] = useState(false);
  const [total, setTotal] = useState(null);
  const [grouped, setGrouped] = useState(null);
  const [budget, setBudget] = useState(null);
  const [error, setError] = useState(null);
  const prefs = getPrefs();

  useEffect(() => { listResourceGroups().then(setRgs).catch(() => setRgs([])); listBudgets().then((bs) => setBudget(bs[0] || null)).catch(() => {}); }, []);

  const filter = useMemo(() => toBudgetFilter(rgFilter), [rgFilter]);
  useEffect(() => {
    setTotal(null); setError(null);
    costQuery({ type: "ActualCost", timeframe: "MonthToDate", dataset: { filter, aggregation: { totalCost: { name: "Cost", function: "Sum" } } } })
      .then((r) => setTotal(r.properties.rows[0]?.[0] || 0)).catch((e) => setError(e));
  }, [filter]);
  useEffect(() => {
    if (groupBy === "None") { setGrouped(null); return; }
    costQuery({ type: "ActualCost", timeframe: "MonthToDate", dataset: { filter, grouping: [{ type: "Dimension", name: GROUPINGS[groupBy] }] } })
      .then((r) => setGrouped(r.properties.rows)).catch(() => setGrouped([]));
  }, [groupBy, filter]);

  const forecast = total == null ? null : view === "Daily costs" || granularity === "Daily" ? total / new Date().getDate() : total * 30.4 / new Date().getDate();

  return (
    <CostShell active="analysis">
      <div className="vy-page">
        <section className="vy-form-section">
          <h3>View</h3>
          <div className="vy-form-row"><label>View</label><div>
            <Select value={view} onChange={(_, d) => setView(d.value)} aria-label="View">
              {["Accumulated costs", "Daily costs", "Cost by service", "Invoice details"].map((o) => <option key={o}>{o}</option>)}
            </Select>
          </div></div>
          <div className="vy-form-row"><label>Date range</label><div>
            <Select value="This month" onChange={() => {}} aria-label="Date range"><option>This month</option></Select>
          </div></div>
          <div className="vy-form-row"><label>Add filter</label><div>
            <Button onClick={() => setShowFilter((v) => !v)}>Add filter</Button>
            {showFilter && (
              <Select style={{ marginLeft: 8 }} value={rgFilter} onChange={(_, d) => setRgFilter(d.value)} aria-label="Filter by resource group">
                <option value="">Resource group: all</option>
                {rgs.map((rg) => <option key={rg.name} value={rg.name}>Resource group: {rg.name}</option>)}
              </Select>
            )}
          </div></div>
          <div className="vy-form-row"><label>Group by</label><div>
            <Select value={groupBy} onChange={(_, d) => setGroupBy(d.value)} aria-label="Group by">
              {["None", ...Object.keys(GROUPINGS)].map((o) => <option key={o}>{o}</option>)}
            </Select>
          </div></div>
          <div className="vy-form-row"><label>Granularity</label><div>
            <Select value={granularity} onChange={(_, d) => setGranularity(d.value)} aria-label="Granularity">
              {["Accumulated", "Daily", "Monthly"].map((o) => <option key={o}>{o}</option>)}
            </Select>
          </div></div>
        </section>

        <ErrorBar error={error} title="Cost query failed" />

        <section className="vy-form-section">
          <h3>Totals</h3>
          <div className="vy-kv"><span>Actual cost (USD)</span><span>{total == null ? "Loading..." : DOLLAR(total)}</span></div>
          <div className="vy-kv"><span>Forecast: chart view</span><span>{prefs.forecastPreview ? (forecast == null ? "Loading..." : `on — ${DOLLAR(forecast)} projected`) : "off (enable in Preview features)"}</span></div>
          <div className="vy-kv"><span>Budget</span><span>{budget ? `${budget.name} (${DOLLAR(budget.properties.amount)})` : "none"}</span></div>
          {groupBy !== "None" && grouped && (
            <Table size="small" aria-label={`Cost by ${groupBy}`} style={{ marginTop: 12 }}>
              <TableHeader><TableRow><TableHeaderCell>{groupBy}</TableHeaderCell><TableHeaderCell>Cost</TableHeaderCell></TableRow></TableHeader>
              <TableBody>{grouped.map(([cost, key]) => <TableRow key={key}><TableCell>{key}</TableCell><TableCell>{DOLLAR(cost)}</TableCell></TableRow>)}</TableBody>
            </Table>
          )}
        </section>

        <Breakdown title="Service name" dim="ServiceName" />
        <Breakdown title="Location" dim="ResourceLocation" />
        <Breakdown title="Resource group name" dim="ResourceGroupName" />
      </div>
    </CostShell>
  );
}
