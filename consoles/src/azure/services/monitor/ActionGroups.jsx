import { useEffect, useState } from "react";
import { Button } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { deleteActionGroup, listActionGroups } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";

const receiverCount = (p) => ["emailReceivers", "smsReceivers", "webhookReceivers", "itsmReceivers", "azureAppPushReceivers",
  "automationRunbookReceivers", "voiceReceivers", "logicAppReceivers", "azureFunctionReceivers", "armRoleReceivers", "eventHubReceivers"]
  .reduce((n, k) => n + (p[k]?.length || 0), 0);

export default function ActionGroups() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = () => { setLoading(true); setError(null); listActionGroups().then(setItems).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);

  const columns = [
    { key: "name", label: "Name" },
    { key: "shortname", label: "Short name", value: (g) => g.properties.groupShortName },
    { key: "rg", label: "Resource group", value: (g) => g.resourceGroup },
    { key: "enabled", label: "Enabled", value: (g) => (g.properties.enabled ? "Yes" : "No") },
    { key: "receivers", label: "Actions", value: (g) => `${receiverCount(g.properties)} action(s)` },
  ];

  return (
    <MonitorShell active="alerts" pageTitle="Action groups">
      <CapabilityContainer id="azure.monitor.action_groups" title="Action groups">
        <BrowseGrid resourceName="action group" items={items} columns={columns} loading={loading} error={error}
          onRefresh={load} onCreate={() => { location.hash = "#/monitor/createactiongroup"; }}
          onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteActionGroup(r.resourceGroup, r.name))); load(); }}
          emptyAction={<Button appearance="primary" as="a" href="#/monitor/createactiongroup">Create action group</Button>}
          csvName="action-groups.csv" />
      </CapabilityContainer>
    </MonitorShell>
  );
}
