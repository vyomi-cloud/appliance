import { useEffect, useState } from "react";
import { Button } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { deleteAutoscaleSetting, listAutoscaleSettings } from "./api.js";
import { parseId } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";

const resourceType = (s) => (s.properties.targetResourceUri ? parseId(s.properties.targetResourceUri).provider + "/" + s.properties.targetResourceUri.split("/providers/")[1]?.split("/")[1] : "--");

export default function Autoscale() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const load = () => { setLoading(true); setError(null); listAutoscaleSettings().then(setItems).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);

  const columns = [
    { key: "name", label: "Name" },
    { key: "type", label: "Resource type", value: resourceType },
    { key: "rg", label: "Resource group", value: (s) => s.resourceGroup },
    { key: "loc", label: "Location", value: (s) => s.location },
    { key: "count", label: "Instance count", value: (s) => s.properties.profiles?.[0]?.capacity?.default },
    { key: "status", label: "Autoscale status", value: (s) => (s.properties.enabled ? "Enabled" : "Disabled") },
  ];

  return (
    <MonitorShell active="autoscale">
      <CapabilityContainer id="azure.monitor.autoscale" title="Autoscale">
        <BrowseGrid resourceName="autoscale setting" items={items} columns={columns} loading={loading} error={error}
          onRefresh={load} onCreate={() => { location.hash = "#/monitor/createautoscale"; }}
          onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteAutoscaleSetting(r.resourceGroup, r.name))); load(); }}
          emptyAction={<Button appearance="primary" as="a" href="#/monitor/createautoscale">Add an autoscale setting</Button>}
          csvName="autoscale.csv" />
      </CapabilityContainer>
    </MonitorShell>
  );
}
