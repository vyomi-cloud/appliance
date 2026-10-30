import { useEffect, useState } from "react";
import { Tab, TabList, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { deleteDataCollectionRule, listDataCollectionRules } from "./api.js";
import { locationLabel } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading, NotSimulatedContainer } from "../../kit/common.jsx";

export default function DataCollectionRules() {
  const [tab, setTab] = useState("overview");
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const load = () => { setError(null); listDataCollectionRules().then(setItems).catch(setError); };
  useEffect(load, []);

  const destinations = new Set((items || []).flatMap((r) => (r.properties.destinations?.logAnalytics || []).map((d) => d.workspaceResourceId)));

  const columns = [
    { key: "name", label: "Name" },
    { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
    { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
    { key: "kind", label: "Kind", value: () => "Linux and Windows" },
  ];

  return (
    <MonitorShell active="datacollectionrules">
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Data Collection Rules">
        <Tab value="overview">Overview</Tab>
        <Tab value="rules">Data collection rules</Tab>
        <Tab value="resources">Resources</Tab>
      </TabList>
      {tab === "overview" && (
        <section className="vy-form-section" style={{ marginTop: 12 }}>
          <h3>Summary</h3>
          {items === null ? <Loading /> : (
            <div className="vy-essentials-grid">
              <div><div className="vy-kv"><span>Data collection rules</span><span>{items.length}</span></div></div>
              <div><div className="vy-kv"><span>Destinations</span><span>{destinations.size}</span></div></div>
            </div>
          )}
        </section>
      )}
      {tab === "resources" && <NotSimulatedContainer title="Resources" note="Resource-to-rule associations aren't modelled; counts of Resources collecting / Not collecting aren't available." />}
      {tab !== "resources" && (
        <CapabilityContainer id="azure.monitor.data_collection_rules" title="Data collection rules" actions={
          <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
            <ToolbarButton icon={<Add20Regular />} as="a" href="#/monitor/createdatacollectionrule">Create a data collection rule</ToolbarButton>
          </div>
        }>
          <NotSimulatedContainer title="Not simulated in Vyomi" note="Use preview, Feedback." />
          {items === null ? <Loading /> : (
            <BrowseGrid resourceName="data collection rule" items={items} columns={columns} loading={false} error={error}
              onRefresh={load} onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteDataCollectionRule(r.resourceGroup, r.name))); load(); }}
              csvName="data-collection-rules.csv" />
          )}
        </CapabilityContainer>
      )}
    </MonitorShell>
  );
}
