import { useEffect, useState } from "react";
import { Button, Select, Tab, TabList } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import { listAllResources, LOCATIONS_OF, RESOURCE_TYPES } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading } from "../../kit/common.jsx";

export default function Metrics() {
  const [tab, setTab] = useState("browse");
  const [resources, setResources] = useState(null);
  const [resourceType, setResourceType] = useState("All resource types");
  const [locationFilter, setLocationFilter] = useState("All locations");
  const [applied, setApplied] = useState({ resourceType: "All resource types", locationFilter: "All locations" });

  useEffect(() => { listAllResources().then(setResources).catch(() => setResources([])); }, []);

  const locations = resources ? LOCATIONS_OF(resources) : [];
  const filtered = (resources || []).filter((r) =>
    (applied.resourceType === "All resource types" || `${r.resourceType}` === applied.resourceType) &&
    (applied.locationFilter === "All locations" || r.location === applied.locationFilter));

  return (
    <MonitorShell active="metrics">
      <div className="vy-cmdbar" role="toolbar" aria-label="Command bar" style={{ marginBottom: 8 }}>
        <Button appearance="subtle" disabled>New chart</Button>
        <Button appearance="subtle" disabled>Share</Button>
        <span className="vy-pill vy-pill-static">Local Time: Last 24 hours (Automatic)</span>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Metrics">
        <Tab value="browse">Browse</Tab>
        <Tab value="recent">Recent</Tab>
      </TabList>
      {tab === "recent" ? (
        <p style={{ marginTop: 12 }}>No recently viewed charts yet.</p>
      ) : (
        <>
          <CapabilityContainer id="azure.monitor.metrics_scope" title="Select a scope">
            <FormRow label="Resource types">
              <Select value={resourceType} onChange={(_, d) => setResourceType(d.value)} aria-label="Resource types">
                <option>All resource types</option>
                {RESOURCE_TYPES.map((rt) => <option key={rt.type} value={`${rt.provider}/${rt.type}`}>{rt.label}</option>)}
              </Select>
            </FormRow>
            <FormRow label="Locations">
              <Select value={locationFilter} onChange={(_, d) => setLocationFilter(d.value)} aria-label="Locations">
                <option>All locations</option>
                {locations.map((l) => <option key={l} value={l}>{l}</option>)}
              </Select>
            </FormRow>
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <Button appearance="primary" onClick={() => setApplied({ resourceType, locationFilter })}>Apply</Button>
              <Button onClick={() => { setResourceType("All resource types"); setLocationFilter("All locations"); setApplied({ resourceType: "All resource types", locationFilter: "All locations" }); }}>Cancel</Button>
            </div>
            {resources === null ? <Loading /> : (
              <p style={{ marginTop: 8 }}>{filtered.length} resource{filtered.length === 1 ? "" : "s"} in scope: {filtered.map((r) => r.name).join(", ") || "none"}.</p>
            )}
          </CapabilityContainer>

          <CapabilityContainer id="azure.monitor.metrics_charts" title="Chart Title" />
        </>
      )}
    </MonitorShell>
  );
}

function FormRow({ label, children }) {
  return <div className="vy-form-row"><label>{label}</label><div>{children}</div></div>;
}
