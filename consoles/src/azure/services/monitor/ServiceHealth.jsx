/* Service health: there is no real Azure platform behind Vyomi to go down, so a fabricated
 * incident feed would be dishonest. This instead lists the REAL resource provider namespaces
 * this environment registers (GET /subscriptions/{sub}/providers) — every one Available,
 * because that is literally true: Vyomi injects no faults. */
import { useEffect, useState } from "react";
import { Tab, TabList, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import { listProviders } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading } from "../../kit/common.jsx";

export default function ServiceHealth() {
  const [tab, setTab] = useState("overview");
  const [providers, setProviders] = useState(null);
  useEffect(() => { listProviders().then(setProviders).catch(() => setProviders([])); }, []);

  return (
    <MonitorShell active="servicehealth" pageTitle="Service health">
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Service health">
        <Tab value="overview">Overview</Tab>
        <Tab value="history">Status history</Tab>
      </TabList>
      <CapabilityContainer id="azure.monitor.service_health" title="Service issues" actions={null}>
        {providers === null ? <Loading /> : (
          <>
            <p>{providers.length} resource provider{providers.length === 1 ? "" : "s"} registered in this subscription — all Available.</p>
            <Table size="small" aria-label="Service health">
              <TableHeader><TableRow><TableHeaderCell>Service</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell></TableRow></TableHeader>
              <TableBody>
                {providers.map((p) => <TableRow key={p.namespace}><TableCell>{p.namespace}</TableCell><TableCell>Available</TableCell></TableRow>)}
              </TableBody>
            </Table>
          </>
        )}
      </CapabilityContainer>
      {tab === "history" && (
        <section className="vy-form-section">
          <h3>Status history</h3>
          <p>No issues recorded — Vyomi has no fault-injection, so every modelled resource provider has always been Available.</p>
        </section>
      )}
    </MonitorShell>
  );
}
