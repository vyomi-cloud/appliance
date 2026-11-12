import { useEffect, useState } from "react";
import { Button, Input } from "@fluentui/react-components";
import CostShell from "./CostShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { deleteExport, listExports, putExport, runExport } from "./api.js";
import { ErrorBar, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

const DOLLAR = (n) => (n == null ? "--" : `$${Number(n).toFixed(2)}`);

export default function Exports() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  const load = () => { setLoading(true); setError(null); listExports().then(setItems).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);

  const columns = [
    { key: "name", label: "Name" },
    { key: "format", label: "Format", value: (e) => e.properties.format },
    { key: "last", label: "Last run", value: (e) => fmtDate(e.properties.lastRunTime) },
    { key: "cost", label: "Last run cost (USD)", value: (e) => DOLLAR(e.properties.lastRunCost?.amount) },
  ];

  return (
    <CostShell active="exports">
      <div className="vy-page">
        <CapabilityContainer id="azure.cost.exports" title="Exports" actions={
          <Button appearance="primary" onClick={() => setCreating((v) => !v)}>{creating ? "Cancel" : "Add"}</Button>
        }>
          {creating && (
            <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "0 0 12px" }}>
              <Input placeholder="Export name" value={name} onChange={(_, d) => setName(d.value)} aria-label="Export name" />
              <Button appearance="primary" disabled={!name} onClick={async () => {
                await putExport(name, { properties: { format: "Csv", definition: { type: "ActualCost", timeframe: "MonthToDate" } } });
                setName(""); setCreating(false); load();
              }}>Create</Button>
            </div>
          )}
          <ErrorBar error={error} title="Failed to load exports" />
          <BrowseGrid resourceName="export" items={items} columns={columns} loading={loading} error={error}
            onRefresh={load} onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteExport(r.name))); load(); }}
            extraCommands={<Button size="small" disabled={!items.length} onClick={async () => { await runExport(items[0].name); load(); }}>Run now</Button>}
            csvName="exports.csv" />
        </CapabilityContainer>
      </div>
    </CostShell>
  );
}
