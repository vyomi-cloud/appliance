/* RDS > Service health dashboard (capability rds.service-health): live probes of this environment's RDS API. */
import ServiceHealthPage from "../../kit/ServiceHealth.jsx";
import * as api from "./api.js";

const BAD = /^(failed|incompatible-.*|storage-full|inaccessible-encryption-credentials.*|restore-error)$/;

export const probes = [
  { name: "Amazon RDS API (us-east-1)", run: async () => { const t0 = performance.now(); const xs = await api.describeDBInstances(); return { ok: true, detail: `DescribeDBInstances answered in ${Math.round(performance.now() - t0)} ms (${xs.length} instance${xs.length === 1 ? "" : "s"})` }; } },
  { name: "DB instance states", run: async () => { const xs = await api.describeDBInstances(); const bad = xs.filter((d) => BAD.test(d.DBInstanceStatus || "")); return { ok: bad.length === 0, detail: bad.length ? `${bad.length} instance(s) unhealthy: ${bad.map((d) => `${d.DBInstanceIdentifier} (${d.DBInstanceStatus})`).join(", ")}` : `${xs.length} instance(s) checked, none failed` }; } },
  { name: "DB snapshots", run: async () => { const xs = await api.describeDBSnapshots(); const bad = xs.filter((s) => s.Status === "failed"); return { ok: bad.length === 0, detail: bad.length ? `${bad.length} snapshot(s) failed` : `${xs.length} snapshot(s) checked, none failed` }; } },
  { name: "Recent events", run: async () => { const xs = await api.describeEvents(); const bad = xs.filter((e) => /fail|error/i.test(e.Message || "")); return { ok: bad.length === 0, detail: bad.length ? `${bad.length} failure event(s), latest: ${bad[0].Message}` : `${xs.length} event(s), none reporting failures` }; } },
];

export default function RdsServiceHealth() {
  return <ServiceHealthPage title="Service health dashboard" service="Amazon RDS" probes={probes} />;
}
