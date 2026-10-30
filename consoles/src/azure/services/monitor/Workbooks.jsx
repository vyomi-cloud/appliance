import { useEffect, useState } from "react";
import { Button, Tab, TabList, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { deleteWorkbook, listWorkbooks, putWorkbook } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";

export default function Workbooks() {
  const [tab, setTab] = useState("workbooks");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const load = () => { setLoading(true); setError(null); listWorkbooks().then(setItems).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);

  const quickStart = async (template) => {
    const name = `wb-${Date.now().toString(36)}`;
    await putWorkbook("cloudlearn-rg", name, { location: "eastus", properties: {
      displayName: template === "Dashboard" ? "New dashboard" : "New workbook", category: "workbook",
      serializedData: template === "Dashboard" ? JSON.stringify({ version: "Notebook/1.0", items: [{ type: 1, content: { json: "# Dashboard" } }] }) : "{}",
    } });
    load();
  };

  const columns = [
    { key: "name", label: "Title", value: (w) => w.properties.displayName },
    { key: "rg", label: "Resource group", value: (w) => w.resourceGroup },
    { key: "category", label: "Category", value: (w) => w.properties.category },
  ];

  return (
    <MonitorShell active="workbooks" pageTitle="Gallery">
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Gallery">
        <Tab value="workbooks">Workbooks</Tab>
        <Tab value="public">Public templates</Tab>
        <Tab value="mine">My templates</Tab>
      </TabList>
      {tab !== "workbooks" ? (
        <p style={{ marginTop: 12 }}>No templates to display.</p>
      ) : (
        <div style={{ marginTop: 12 }}>
          <CapabilityContainer id="azure.monitor.workbooks" title="Quick start" actions={
            <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
              <ToolbarButton icon={<Add20Regular />} as="a" href="#/monitor/createworkbook">New</ToolbarButton>
            </div>
          }>
            <div style={{ display: "flex", gap: 8 }}>
              <Button onClick={() => quickStart("Empty")}>Empty</Button>
              <Button onClick={() => quickStart("Dashboard")}>Dashboard</Button>
            </div>
          </CapabilityContainer>
          <BrowseGrid resourceName="workbook" items={items} columns={columns} loading={loading} error={error}
            onRefresh={load} onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteWorkbook(r.resourceGroup, r.name))); load(); }}
            csvName="workbooks.csv" />
        </div>
      )}
    </MonitorShell>
  );
}
