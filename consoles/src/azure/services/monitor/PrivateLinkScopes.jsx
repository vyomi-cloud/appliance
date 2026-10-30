import { useEffect, useState } from "react";
import { ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { deletePrivateLinkScope, listPrivateLinkScopes } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading } from "../../kit/common.jsx";

export default function PrivateLinkScopes() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const load = () => { setError(null); listPrivateLinkScopes().then(setItems).catch(setError); };
  useEffect(load, []);

  const columns = [
    { key: "name", label: "Name" },
    { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
    { key: "query", label: "Query access mode", value: (r) => r.properties.accessModeSettings?.queryAccessMode },
    { key: "ingest", label: "Ingestion access mode", value: (r) => r.properties.accessModeSettings?.ingestionAccessMode },
  ];

  return (
    <MonitorShell active="privatelinkscopes">
      <CapabilityContainer id="azure.monitor.private_link_scopes" title="Azure Monitor Private Link Scopes" actions={
        <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
          <ToolbarButton icon={<Add20Regular />} as="a" href="#/monitor/createprivatelinkscope">Create</ToolbarButton>
        </div>
      }>
        {items === null ? <Loading /> : (
          <BrowseGrid resourceName="private link scope" items={items} columns={columns} loading={false} error={error}
            onRefresh={load} onCreate={() => { location.hash = "#/monitor/createprivatelinkscope"; }}
            onDelete={async (rows) => { await Promise.all(rows.map((r) => deletePrivateLinkScope(r.resourceGroup, r.name))); load(); }}
            csvName="private-link-scopes.csv" />
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
