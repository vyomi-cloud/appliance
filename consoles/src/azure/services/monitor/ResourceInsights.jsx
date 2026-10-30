/* The "Insights" per-resource-type dashboards (Applications, Virtual Machines, Storage
 * accounts, Networks, Azure Cosmos DB, Key Vaults, Service Bus): real inventory for the type,
 * over the generic ARM store — no request/exception telemetry or health rollup (not modelled). */
import { useEffect, useState } from "react";
import { Button, Select } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { listResourcesOfType } from "./api.js";
import { locationLabel } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";

const TIME_RANGES = ["Last 24 hours", "Last 7 days", "Last 30 days"];

export default function ResourceInsights({ active, pageTitle, resourceType, createHref, withFilters }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [timeRange, setTimeRange] = useState(TIME_RANGES[0]);
  const load = () => { setLoading(true); setError(null); listResourcesOfType(resourceType).then(setItems).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, [resourceType]);

  const columns = [
    { key: "name", label: "Name" },
    { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
    { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
  ];

  return (
    <MonitorShell active={active} pageTitle={pageTitle}>
      {withFilters && (
        <section className="vy-form-section">
          <h3>Filters</h3>
          <div className="vy-form-row"><label>Subscriptions</label><div><span className="vy-pill vy-pill-static" title="Vyomi simulates one subscription">Vyomi subscription</span></div></div>
          <div className="vy-form-row"><label>Time Range</label><div>
            <Select value={timeRange} onChange={(_, d) => setTimeRange(d.value)} aria-label="Time Range">{TIME_RANGES.map((t) => <option key={t}>{t}</option>)}</Select>
          </div></div>
        </section>
      )}
      <CapabilityContainer id="azure.monitor.resource_insights" title={`${resourceType.label} inventory`}>
        <BrowseGrid resourceName={resourceType.label.toLowerCase()} items={items} columns={columns} loading={loading} error={error}
          onRefresh={load} onCreate={createHref ? () => { location.hash = createHref; } : undefined}
          emptyAction={createHref ? <Button appearance="primary" as="a" href={createHref}>Create one</Button> : undefined}
          csvName={`${resourceType.type.toLowerCase()}.csv`} />
      </CapabilityContainer>
    </MonitorShell>
  );
}
