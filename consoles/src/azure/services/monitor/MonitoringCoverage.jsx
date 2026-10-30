import { useEffect, useState } from "react";
import { Tab, TabList, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import { listAlertRules, listAllResources } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading } from "../../kit/common.jsx";

/** A resource counts as "covered" when it is referenced in at least one alert rule's scopes. */
function useCoverage() {
  const [data, setData] = useState(null);
  useEffect(() => {
    Promise.all([listAllResources(), listAlertRules()]).then(([resources, rules]) => {
      const covered = new Set(rules.flatMap((r) => r.scopes || []).map((s) => s.toLowerCase()));
      setData({ resources, covered: resources.filter((r) => covered.has(r.id.toLowerCase())), ruleCount: rules.length });
    }).catch(() => setData({ resources: [], covered: [], ruleCount: 0 }));
  }, []);
  return data;
}

export default function MonitoringCoverage() {
  const [tab, setTab] = useState("overview");
  const data = useCoverage();

  return (
    <MonitorShell active="monitoringcoverage">
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Monitoring Coverage">
        <Tab value="overview">Overview</Tab>
        <Tab value="details">Monitoring Details</Tab>
      </TabList>
      <CapabilityContainer id="azure.monitor.monitoring_coverage" title="Summary">
        {data === null ? <Loading /> : (
          <p>{data.covered.length} of {data.resources.length} resources have at least one alert rule covering them ({data.ruleCount} alert rule{data.ruleCount === 1 ? "" : "s"} total).</p>
        )}
        <section className="vy-form-section">
          <h3>Infrastructure coverage</h3>
          {data && <p>{data.resources.filter((r) => ["virtualMachines", "storageAccounts"].some((t) => r.resourceType.endsWith(t))).length} infrastructure resources in inventory.</p>}
        </section>
        <section className="vy-form-section">
          <h3>Platform telemetry coverage</h3>
          {data && <p>{data.resources.filter((r) => ["sites", "databaseAccounts", "vaults", "namespaces"].some((t) => r.resourceType.endsWith(t))).length} platform resources in inventory.</p>}
        </section>
        {tab === "details" && data && (
          <Table size="small" aria-label="Monitoring details">
            <TableHeader><TableRow><TableHeaderCell>Resource</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell><TableHeaderCell>Coverage</TableHeaderCell></TableRow></TableHeader>
            <TableBody>
              {data.resources.map((r) => (
                <TableRow key={r.id}><TableCell>{r.name}</TableCell><TableCell>{r.typeLabel}</TableCell>
                  <TableCell>{data.covered.includes(r) ? "Covered" : "Not covered"}</TableCell></TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
