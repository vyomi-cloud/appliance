/* Health models (preview): a named collection of member resources (Microsoft.Insights/
 * healthModels — real CRUD, core/azure_monitor_core.py). Per-member health and the model's
 * rollup are computed here from the real Activity log's status field (never stored, never
 * fabricated) — "Critical" means that member has a real failed operation right now. */
import { useEffect, useState } from "react";
import { Button, Input } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { listHealthModels, putHealthModel, deleteHealthModel, listAllResources, listFailedActivity } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";

function rollup(model, failedResourceIds) {
  const unhealthy = (model.properties.resources || []).filter((id) => failedResourceIds.has(id.toLowerCase()));
  return unhealthy.length ? `Critical (${unhealthy.length} of ${model.properties.resources.length} unhealthy)` : "Healthy";
}

export default function HealthModels() {
  const [models, setModels] = useState(null);
  const [resources, setResources] = useState([]);
  const [failedIds, setFailedIds] = useState(new Set());
  const [error, setError] = useState(null);
  const [name, setName] = useState("");
  const [picked, setPicked] = useState(new Set());
  const [createError, setCreateError] = useState(null);

  const load = () => {
    setError(null);
    Promise.all([listHealthModels(), listAllResources(), listFailedActivity()]).then(([ms, rs, failed]) => {
      setModels(ms); setResources(rs);
      setFailedIds(new Set(failed.map((f) => (f.resourceId || "").toLowerCase())));
    }).catch(setError);
  };
  useEffect(load, []);

  const toggle = (id) => setPicked((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const create = async () => {
    if (!name || picked.size === 0) return;
    setCreateError(null);
    try {
      await putHealthModel("cloudlearn-rg", name.replace(/[^a-zA-Z0-9-]/g, "-"), {
        location: "global", properties: { displayName: name, resources: [...picked] },
      });
      setName(""); setPicked(new Set()); load();
    } catch (e) { setCreateError(e); }
  };

  const columns = [
    { key: "name", label: "Name", value: (r) => r.properties.displayName || r.name },
    { key: "resources", label: "Resources", value: (r) => r.properties.resources.length },
    { key: "health", label: "Health", value: (r) => rollup(r, failedIds) },
  ];

  return (
    <MonitorShell active="healthmodels" pageTitle="Health models">
      <CapabilityContainer id="azure.monitor.health_models" title="Health models">
        <section className="vy-form-section">
          <h3>New health model</h3>
          <div className="vy-form-row"><label>Display name</label><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Display name" /></div>
          <div className="vy-form-row"><label>Member resources</label>
            <div style={{ maxHeight: 140, overflow: "auto", border: "1px solid #ddd", padding: 6 }}>
              {resources.map((r) => (
                <label key={r.id} style={{ display: "block", fontSize: 13 }}>
                  <input type="checkbox" checked={picked.has(r.id)} onChange={() => toggle(r.id)} /> {r.name} ({r.typeLabel})
                </label>
              ))}
              {resources.length === 0 && <span>No resources yet.</span>}
            </div>
          </div>
          <Button appearance="primary" icon={<Add20Regular />} onClick={create} disabled={!name || picked.size === 0} style={{ marginTop: 8 }}>Create health model</Button>
          <ErrorBar error={createError} />
        </section>
        {models === null ? <Loading /> : (
          <BrowseGrid resourceName="health model" items={models} columns={columns} loading={false} error={error} onRefresh={load}
            onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteHealthModel(r.resourceGroup, r.name))); load(); }}
            csvName="health-models.csv" />
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
