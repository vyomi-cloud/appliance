import { useEffect, useState } from "react";
import { Button } from "@fluentui/react-components";
import CostShell from "./CostShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { deleteBudget, listBudgets, RESET_PERIOD_LABEL } from "./api.js";
import { ErrorBar } from "../../kit/common.jsx";

const DOLLAR = (n) => `$${Number(n || 0).toFixed(2)}`;
const SCOPE_LABEL = (b) => (b.properties._scopeResourceGroup ? `Resource group: ${b.properties._scopeResourceGroup}` : "Subscription");

export default function Budgets() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = () => {
    setLoading(true); setError(null);
    listBudgets().then((v) => setItems(v)).catch(setError).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const columns = [
    { key: "name", label: "Name" },
    { key: "scope", label: "Scope", value: SCOPE_LABEL },
    { key: "reset", label: "Reset period", value: (b) => RESET_PERIOD_LABEL[b.properties.timeGrain] || b.properties.timeGrain },
    { key: "amount", label: "Amount", value: (b) => DOLLAR(b.properties.amount) },
    { key: "spend", label: "Evaluated spend", value: (b) => DOLLAR(b.properties.currentSpend?.amount) },
    { key: "forecast", label: "Forecast", value: (b) => DOLLAR(b.properties.forecastSpend?.amount) },
    { key: "progress", label: "Progress", value: (b) => `${Math.min(100, Math.round((b.properties.currentSpend?.amount / b.properties.amount) * 100 || 0))}%` },
  ];

  return (
    <CostShell active="budgets">
      <div className="vy-page">
        <ErrorBar error={error} title="Failed to load budgets" />
        <BrowseGrid resourceName="budget" items={items} columns={columns} loading={loading} error={error}
          onRefresh={load} onCreate={() => { location.hash = "#/cost/budgets/create"; }}
          onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteBudget(r.name))); load(); }}
          emptyAction={<Button appearance="primary" as="a" href="#/cost/budgets/create">Add a budget</Button>} csvName="budgets.csv" />
      </div>
    </CostShell>
  );
}
