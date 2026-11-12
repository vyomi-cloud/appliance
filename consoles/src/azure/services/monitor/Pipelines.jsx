/* Azure Monitor pipelines (preview): the collector-fleet configuration (platform + endpoints a
 * group of OpenTelemetry collectors would forward to) is real CRUD (Microsoft.Insights/
 * pipelineGroups, core/azure_monitor_core.py) — the same "config real, data never actually
 * flows" shape as Data Collection Endpoints, since there is no on-premises collector fleet to
 * run inside a browser-based simulator. */
import { useEffect, useState } from "react";
import { Button, Input, Select } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { listPipelineGroups, putPipelineGroup, deletePipelineGroup } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";

export default function Pipelines() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState("Linux");
  const [endpoint, setEndpoint] = useState("");
  const [createError, setCreateError] = useState(null);

  const load = () => { setError(null); listPipelineGroups().then(setItems).catch(setError); };
  useEffect(load, []);

  const create = async () => {
    if (!name) return;
    setCreateError(null);
    try {
      await putPipelineGroup("cloudlearn-rg", name, { location: "eastus", properties: { platform, collectorEndpoints: endpoint ? [endpoint] : [] } });
      setName(""); setEndpoint(""); load();
    } catch (e) { setCreateError(e); }
  };

  const columns = [
    { key: "name", label: "Name" },
    { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
    { key: "platform", label: "Platform", value: (r) => r.properties.platform },
    { key: "endpoints", label: "Collector endpoints", value: (r) => r.properties.collectorEndpoints.join(", ") || "--" },
  ];

  return (
    <MonitorShell active="pipelines" pageTitle="Azure Monitor pipelines">
      <CapabilityContainer id="azure.monitor.pipelines" title="Azure Monitor pipelines">
        <section className="vy-form-section">
          <h3>New pipeline group</h3>
          <div className="vy-form-row"><label>Name</label><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></div>
          <div className="vy-form-row"><label>Platform</label>
            <Select value={platform} onChange={(_, d) => setPlatform(d.value)} aria-label="Platform"><option>Linux</option><option>Windows</option></Select>
          </div>
          <div className="vy-form-row"><label>Collector endpoint</label><Input value={endpoint} onChange={(_, d) => setEndpoint(d.value)} placeholder="https://..." aria-label="Collector endpoint" /></div>
          <Button appearance="primary" icon={<Add20Regular />} onClick={create} disabled={!name} style={{ marginTop: 8 }}>Create pipeline group</Button>
          <ErrorBar error={createError} />
        </section>
        {items === null ? <Loading /> : (
          <BrowseGrid resourceName="pipeline group" items={items} columns={columns} loading={false} error={error} onRefresh={load}
            onDelete={async (rows) => { await Promise.all(rows.map((r) => deletePipelineGroup(r.resourceGroup, r.name))); load(); }}
            csvName="pipelines.csv" />
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
