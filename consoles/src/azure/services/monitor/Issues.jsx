/* Issues: Vyomi has no cross-signal (metrics + logs + availability) ML correlation engine, so
 * this groups the one real failure signal the backend produces — Activity log rows whose
 * status isn't Succeeded (core/azure_arm_core.py logs status="Failed" when a real ARM template
 * deployment fails its real evaluation) — by resource. Never a fabricated incident feed. */
import { useEffect, useState } from "react";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { listFailedActivity } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading } from "../../kit/common.jsx";

function groupByResource(rows) {
  const byResource = new Map();
  for (const r of rows) {
    const key = r.resourceId || r.operationName?.value || "unknown";
    const g = byResource.get(key) || { id: key, resource: r.resourceId, operations: [], lastTime: r.eventTimestamp };
    g.operations.push(r.operationName?.value || r.operationName);
    if (r.eventTimestamp > g.lastTime) g.lastTime = r.eventTimestamp;
    byResource.set(key, g);
  }
  return [...byResource.values()].map((g) => ({ ...g, name: (g.resource || g.id).split("/").pop(), count: g.operations.length }));
}

export default function Issues() {
  const [issues, setIssues] = useState(null);
  const [error, setError] = useState(null);
  const load = () => { setError(null); listFailedActivity().then((rows) => setIssues(groupByResource(rows))).catch(setError); };
  useEffect(load, []);

  const columns = [
    { key: "name", label: "Resource" },
    { key: "count", label: "Failed operations", value: (r) => r.count },
    { key: "ops", label: "Operations", value: (r) => r.operations.join(", ") },
    { key: "time", label: "Last seen", value: (r) => r.lastTime },
  ];

  return (
    <MonitorShell active="issues" pageTitle="Issues">
      <CapabilityContainer id="azure.monitor.issues" title="Issues">
        {issues === null ? <Loading /> : (
          <BrowseGrid resourceName="issue" items={issues} columns={columns} loading={false} error={error} onRefresh={load}
            emptyAction={<p>No resource has a failed Activity log operation right now.</p>} csvName="issues.csv" />
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
