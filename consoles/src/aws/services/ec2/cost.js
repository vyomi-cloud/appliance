/* EC2 cost estimate: what the account's CURRENT EC2 resources would cost on real AWS at list prices (us-east-1, on-demand), next to what
 * Vyomi charges ($0.00). Pure functions over the resource lists the console already reads from the wire; prices come from
 * price-table.json, generated from core/cost_model.py (tests/conformance/test_ec2_cost_table.py keeps them in sync). */
import prices from "./price-table.json";

const GB = (v) => Number(v) || 0;

/** instances: DescribeInstances rows; volumes: DescribeVolumes rows; addresses: DescribeAddresses rows; snapshots: DescribeSnapshots rows; nats: NAT gateways. */
export function estimateCost({ instances = [], volumes = [], addresses = [], snapshots = [], nats = [] }, nowMs = Date.now()) {
  const rows = [];
  const hoursSince = (t) => { const ms = Date.parse(t); return Number.isFinite(ms) ? Math.max(0, (nowMs - ms) / 3600000) : 0; };
  for (const i of instances) {
    if (i.instanceState?.name !== "running") continue;
    const rate = prices.vmHourly[i.instanceType] ?? prices.defaultVmHourly;
    rows.push({ type: "Instances (running)", id: i.instanceId, detail: i.instanceType, hourly: rate, monthly: rate * prices.hoursPerMonth, toDate: rate * hoursSince(i.launchTime) });
  }
  for (const v of volumes) {
    const gbMo = prices.ebsGbMonth[v.volumeType] ?? prices.ebsGbMonth.gp3;
    const monthly = GB(v.size) * gbMo;
    rows.push({ type: "EBS volumes", id: v.volumeId, detail: `${v.size} GiB ${v.volumeType}`, hourly: monthly / prices.hoursPerMonth, monthly, toDate: monthly / prices.hoursPerMonth * hoursSince(v.createTime) });
  }
  for (const s of snapshots) {
    const monthly = GB(s.volumeSize) * prices.snapshotGbMonth;
    rows.push({ type: "EBS snapshots", id: s.snapshotId, detail: `${s.volumeSize} GiB (full-size upper bound)`, hourly: monthly / prices.hoursPerMonth, monthly, toDate: monthly / prices.hoursPerMonth * hoursSince(s.startTime) });
  }
  for (const a of addresses) {
    rows.push({ type: "Public IPv4 addresses", id: a.allocationId || a.publicIp, detail: a.publicIp, hourly: prices.publicIpv4Hourly, monthly: prices.publicIpv4Hourly * prices.hoursPerMonth, toDate: 0 });
  }
  for (const n of nats) {
    rows.push({ type: "NAT gateways", id: n.natGatewayId, detail: "hourly charge (excl. data)", hourly: prices.natGatewayHourly, monthly: prices.natGatewayHourly * prices.hoursPerMonth, toDate: 0 });
  }
  const sum = (k) => rows.reduce((a, r) => a + r[k], 0);
  const byType = {};
  for (const r of rows) { const b = (byType[r.type] ||= { type: r.type, count: 0, monthly: 0, toDate: 0 }); b.count++; b.monthly += r.monthly; b.toDate += r.toDate; }
  return { rows, byType: Object.values(byType), monthly: sum("monthly"), toDate: sum("toDate"), hourly: sum("hourly") };
}

export const usd = (n) => `$${(Math.round(n * 100) / 100).toFixed(2)}`;
