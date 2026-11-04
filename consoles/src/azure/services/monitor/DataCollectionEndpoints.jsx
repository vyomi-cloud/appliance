import { useEffect, useState } from "react";
import { ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { deleteDataCollectionEndpoint, listDataCollectionEndpoints } from "./api.js";
import { locationLabel } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading } from "../../kit/common.jsx";

export default function DataCollectionEndpoints() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const load = () => { setError(null); listDataCollectionEndpoints().then(setItems).catch(setError); };
  useEffect(load, []);

  const columns = [
    { key: "name", label: "Name" },
    { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
    { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
    { key: "logs", label: "Logs ingestion endpoint", value: (r) => r.properties.logsIngestion?.endpoint || "--" },
  ];

  return (
    <MonitorShell active="datacollectionendpoints">
      <CapabilityContainer id="azure.monitor.data_collection_endpoints" title="Data Collection Endpoints" actions={
        <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
          <ToolbarButton icon={<Add20Regular />} as="a" href="#/monitor/createdatacollectionendpoint">Create</ToolbarButton>
        </div>
      }>
        {items === null ? <Loading /> : (
          <BrowseGrid resourceName="data collection endpoint" items={items} columns={columns} loading={false} error={error}
            onRefresh={load} onCreate={() => { location.hash = "#/monitor/createdatacollectionendpoint"; }}
            onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteDataCollectionEndpoint(r.resourceGroup, r.name))); load(); }}
            csvName="data-collection-endpoints.csv" />
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
