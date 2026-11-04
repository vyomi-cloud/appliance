import { useEffect, useState } from "react";
import { Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, ToolbarButton } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import { listAllResources } from "./api.js";
import { Loading, NotSimulated } from "../../kit/common.jsx";

const SERVICES = [
  { name: "Applications", description: "Application Performance Monitoring for your live web application.", href: "#/monitor/insights-applications" },
  { name: "Virtual Machines", description: "Monitor the performance and health of your virtual machines.", href: "#/monitor/insights-vms" },
  { name: "Storage accounts", description: "Monitor availability, performance, and usage of your storage accounts.", href: "#/monitor/insights-storage" },
  { name: "Containers", description: "Monitor the performance of container workloads.", href: "#/monitor/insights-containers" },
  { name: "Networks", description: "Monitor the health of your network resources.", href: "#/monitor/insights-networks" },
  { name: "Azure Cosmos DB", description: "Monitor throughput, storage, and availability of your databases.", href: "#/monitor/insights-cosmosdb" },
  { name: "Key Vaults", description: "Monitor the availability and latency of your key vaults.", href: "#/monitor/insights-keyvaults" },
  { name: "Azure Cache for Redis", description: "Monitor cache performance and hit ratio.", href: "#/monitor/insights-redis" },
  { name: "Log Analytics workspaces", description: "Monitor the ingestion and health of your workspaces.", href: "#/monitor/loganalyticsworkspaces" },
  { name: "Service Bus (preview)", description: "Monitor message throughput and active connections.", href: "#/monitor/insights-servicebus" },
];

export default function InsightsHub() {
  const [desc, setDesc] = useState(true);
  const [asc, setAsc] = useState(true);
  const [resources, setResources] = useState(null);
  useEffect(() => { listAllResources().then(setResources).catch(() => setResources([])); }, []);
  const rows = [...SERVICES].sort((a, b) => (asc ? 1 : -1) * a.name.localeCompare(b.name));

  return (
    <MonitorShell active="insightshub">
      <section className="vy-form-section">
        <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
          <ToolbarButton onClick={() => setAsc((v) => !v)}>Sort</ToolbarButton>
          <ToolbarButton onClick={() => setDesc(true)}>Expand All</ToolbarButton>
          <ToolbarButton onClick={() => setDesc(false)}>Collapse All</ToolbarButton>
        </div>
        <Table size="small" aria-label="Insights Hub">
          <TableHeader><TableRow><TableHeaderCell>Service Name</TableHeaderCell>{desc && <TableHeaderCell>Description</TableHeaderCell>}</TableRow></TableHeader>
          <TableBody>
            {rows.map((s) => (
              <TableRow key={s.name}>
                <TableCell><a href={s.href}>{s.name}</a></TableCell>
                {desc && <TableCell>{s.description}</TableCell>}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <NotSimulated feature="Feedback" />
      </section>
      <section className="vy-form-section">
        <h3>Your inventory</h3>
        {resources === null ? <Loading /> : !resources.length ? <p>No resources yet.</p> : (
          <p>{resources.map((r) => r.name).join(", ")}</p>
        )}
      </section>
    </MonitorShell>
  );
}
