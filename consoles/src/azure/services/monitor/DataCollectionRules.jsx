import { useEffect, useState } from "react";
import { Tab, TabList, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { deleteDataCollectionRule, listDataCollectionRules, listDcrResources, listResourcesOfType, RESOURCE_TYPES } from "./api.js";
import { locationLabel, parseId } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading } from "../../kit/common.jsx";

const ASSOC_MARK = "/providers/microsoft.insights/datacollectionruleassociations/";

/** Resources tab: the REAL dataCollectionRuleAssociations that name each rule, plus the VMs that have none. */
function ResourcesTab({ rules }) {
  const [rows, setRows] = useState(null);
  const [notCollecting, setNotCollecting] = useState([]);
  const [error, setError] = useState(null);
  const load = () => {
    setError(null);
    (async () => {
      const per = await Promise.all(rules.map(async (r) => (await listDcrResources(r.resourceGroup, r.name)).map((a) => {
        const target = a.id.slice(0, a.id.toLowerCase().indexOf(ASSOC_MARK));
        const p = parseId(target);
        return { id: a.id, name: p.name || target, type: target.split("/providers/")[1]?.split("/").slice(0, 2).join("/") || "--", rg: p.resourceGroup, rule: r.name, assoc: a.name, target };
      })));
      const flat = per.flat();
      setRows(flat);
      const vmType = RESOURCE_TYPES.find((t) => t.type === "virtualMachines");
      const vms = await listResourcesOfType(vmType).catch(() => []);
      const have = new Set(flat.map((x) => x.target.toLowerCase()));
      setNotCollecting(vms.filter((v) => !have.has(v.id.toLowerCase())));
    })().catch(setError);
  };
  useEffect(load, [rules.length]);
  const columns = [
    { key: "name", label: "Resource" },
    { key: "type", label: "Resource type" },
    { key: "rg", label: "Resource group" },
    { key: "rule", label: "Data collection rule" },
    { key: "assoc", label: "Association" },
  ];
  return (
    <CapabilityContainer id="azure.monitor.dcr_resources" title="Resources">
      <div className="vy-essentials-grid" style={{ marginBottom: 8 }}>
        <div><div className="vy-kv"><span>Resources collecting</span><span>{rows ? new Set(rows.map((r) => r.target.toLowerCase())).size : "..."}</span></div></div>
        <div><div className="vy-kv"><span>Virtual machines not collecting</span><span>{rows ? notCollecting.length : "..."}</span></div></div>
      </div>
      {rows === null ? <Loading /> : (
        <BrowseGrid resourceName="resource" items={rows} columns={columns} rowKey={(r) => r.id} loading={false} error={error} onRefresh={load} csvName="dcr-resources.csv" />
      )}
    </CapabilityContainer>
  );
}

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
      {tab === "resources" && (items === null ? <Loading /> : <ResourcesTab rules={items} />)}
      {tab !== "resources" && (
        <CapabilityContainer id="azure.monitor.data_collection_rules" title="Data collection rules" actions={
          <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
            <ToolbarButton icon={<Add20Regular />} as="a" href="#/monitor/createdatacollectionrule">Create a data collection rule</ToolbarButton>
          </div>
        }>
          <p style={{ fontSize: 12 }}><a href="#/monitor/support">Feedback</a> - opens a real support request filed with Vyomi.</p>
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
