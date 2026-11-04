import { useEffect, useState } from "react";
import { Button, Input, Select } from "@fluentui/react-components";
import CostShell from "./CostShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import {
  deleteSavingsPlan, listSavingsPlans, putSavingsPlan,
  SAVINGSPLAN_SCOPES, SAVINGSPLAN_TERM_LABEL, SAVINGSPLAN_TERMS,
} from "./api.js";
import { ErrorBar, fmtDate } from "../../kit/common.jsx";

const RENEWAL_LABEL = (p) => (p.renew ? `On — ${fmtDate(p.expiryDateTime)}` : "Off");

export default function SavingsPlans() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("0.10");
  const [term, setTerm] = useState("P1Y");
  const [appliedScopeType, setAppliedScopeType] = useState("Shared");

  const load = () => { setLoading(true); setError(null); listSavingsPlans().then(setItems).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);

  const columns = [
    { key: "name", label: "Name" },
    { key: "status", label: "Status", value: (p) => p.properties.provisioningState },
    { key: "term", label: "Term", value: (p) => SAVINGSPLAN_TERM_LABEL[p.properties.term] || p.properties.term },
    { key: "scope", label: "Benefit scope", value: (p) => p.properties.appliedScopeType },
    { key: "util", label: "Utilization", value: (p) => `${p.properties.utilization}%` },
    { key: "renewal", label: "Renewal", value: (p) => RENEWAL_LABEL(p.properties) },
  ];

  return (
    <CostShell active="savingsplans">
      <div className="vy-page">
        <CapabilityContainer id="azure.cost.savings_plans" title="Savings plans" actions={
          <Button appearance="primary" onClick={() => setCreating((v) => !v)}>{creating ? "Cancel" : "Purchase"}</Button>
        }>
          {creating && (
            <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "0 0 12px", flexWrap: "wrap" }}>
              <Input placeholder="Savings plan name" value={name} onChange={(_, d) => setName(d.value)} aria-label="Savings plan name" />
              <Input placeholder="Hourly commitment ($)" value={amount} onChange={(_, d) => setAmount(d.value)} aria-label="Hourly commitment" style={{ width: 160 }} />
              <Select value={term} onChange={(_, d) => setTerm(d.value)} aria-label="Term">
                {SAVINGSPLAN_TERMS.map((t) => <option key={t} value={t}>{SAVINGSPLAN_TERM_LABEL[t]}</option>)}
              </Select>
              <Select value={appliedScopeType} onChange={(_, d) => setAppliedScopeType(d.value)} aria-label="Benefit scope">
                {SAVINGSPLAN_SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
              </Select>
              <Button appearance="primary" disabled={!name || !amount} onClick={async () => {
                await putSavingsPlan(name, { properties: { term, appliedScopeType, commitment: { amount: Number(amount), currency: "USD", grain: "Hourly" } } });
                setName(""); setCreating(false); load();
              }}>Create</Button>
            </div>
          )}
          <ErrorBar error={error} title="Failed to load savings plans" />
          <BrowseGrid resourceName="savings plan" items={items} columns={columns} loading={loading} error={error}
            onRefresh={load} onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteSavingsPlan(r.name))); load(); }}
            emptyAction={<Button appearance="primary" onClick={() => setCreating(true)}>Purchase Now</Button>} csvName="savings-plans.csv" />
        </CapabilityContainer>
      </div>
    </CostShell>
  );
}
