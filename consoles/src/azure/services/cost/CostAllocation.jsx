import { useEffect, useState } from "react";
import { Button, Input, Select } from "@fluentui/react-components";
import { Add20Regular, Delete20Regular } from "@fluentui/react-icons";
import CostShell from "./CostShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { deleteAllocationRule, listAllocationRules, putAllocationRule } from "./api.js";
import { listResourceGroups } from "../../kit/arm.js";
import { ErrorBar } from "../../kit/common.jsx";

const SOURCES_LABEL = (r) => (r.properties.details?.sourceResources || []).map((s) => s.name).join(", ");
const TARGETS_LABEL = (r) => (r.properties.details?.targetResources || []).map((t) => `${t.name} (${t.allocation}%)`).join(", ");

export default function CostAllocation() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [sourceRg, setSourceRg] = useState("");
  const [targets, setTargets] = useState([{ name: "", allocation: "100" }]);
  const [rgs, setRgs] = useState([]);

  const load = () => { setLoading(true); setError(null); listAllocationRules().then(setItems).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);
  useEffect(() => { listResourceGroups().then(setRgs).catch(() => setRgs([])); }, []);

  const columns = [
    { key: "name", label: "Rule name" },
    { key: "status", label: "Status", value: (r) => r.properties.status },
    { key: "source", label: "Source resource group", value: SOURCES_LABEL },
    { key: "target", label: "Target resource group(s)", value: TARGETS_LABEL },
    { key: "order", label: "Order", value: (r) => r.properties.order },
  ];

  const update = (i, patch) => setTargets(targets.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  const validTargets = targets.filter((t) => t.name);

  return (
    <CostShell active="allocation">
      <div className="vy-page">
        <CapabilityContainer id="azure.cost.cost_allocation" title="Cost allocation rules" actions={
          <Button appearance="primary" onClick={() => setCreating((v) => !v)}>{creating ? "Cancel" : "Add"}</Button>
        }>
          {creating && (
            <div className="vy-form-section" style={{ margin: "0 0 12px" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
                <Input placeholder="Rule name" value={name} onChange={(_, d) => setName(d.value)} aria-label="Rule name" />
                <Select value={sourceRg} onChange={(_, d) => setSourceRg(d.value)} aria-label="Source resource group">
                  <option value="">Source resource group...</option>
                  {rgs.map((rg) => <option key={rg.name} value={rg.name}>{rg.name}</option>)}
                </Select>
              </div>
              {targets.map((t, i) => (
                <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                  <Select value={t.name} onChange={(_, d) => update(i, { name: d.value })} aria-label="Target resource group">
                    <option value="">Target resource group...</option>
                    {rgs.map((rg) => <option key={rg.name} value={rg.name}>{rg.name}</option>)}
                  </Select>
                  <Input type="number" min="0" max="100" value={t.allocation} onChange={(_, d) => update(i, { allocation: d.value })}
                    aria-label="Allocation percentage" style={{ width: 90 }} />%
                  <Button icon={<Delete20Regular />} appearance="subtle" aria-label="Remove target"
                    onClick={() => setTargets(targets.filter((_, j) => j !== i))} />
                </div>
              ))}
              <Button icon={<Add20Regular />} appearance="subtle" onClick={() => setTargets([...targets, { name: "", allocation: "" }])}>Add a target</Button>
              <div style={{ marginTop: 8 }}>
                <Button appearance="primary" disabled={!name || !sourceRg || !validTargets.length} onClick={async () => {
                  await putAllocationRule(name, { properties: { status: "Active", details: {
                    allocationType: "Fixed",
                    sourceResources: [{ name: sourceRg }],
                    targetResources: validTargets.map((t) => ({ name: t.name, allocation: Number(t.allocation) || 0 })),
                  } } });
                  setName(""); setSourceRg(""); setTargets([{ name: "", allocation: "100" }]); setCreating(false); load();
                }}>Save</Button>
              </div>
            </div>
          )}
          <ErrorBar error={error} title="Failed to load cost allocation rules" />
          <BrowseGrid resourceName="allocation rule" items={items} columns={columns} loading={loading} error={error}
            onRefresh={load} onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteAllocationRule(r.name))); load(); }}
            emptyAction={<Button appearance="primary" onClick={() => setCreating(true)}>Add a rule</Button>} csvName="cost-allocation-rules.csv" />
        </CapabilityContainer>
      </div>
    </CostShell>
  );
}
