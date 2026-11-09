/* VPC > Service health dashboard (capability aws.vpc.service-health): live probes of this environment's VPC / EC2 networking APIs. */
import ServiceHealthPage from "../../kit/ServiceHealth.jsx";
import * as api from "./api.js";
import * as nf from "./apiNfw.js";
import * as ec2 from "../ec2/api.js";

export const probes = [
  { name: "Amazon VPC API (us-east-1)", run: async () => { const t0 = performance.now(); const xs = await api.describeVpcs(); return { ok: true, detail: `DescribeVpcs answered in ${Math.round(performance.now() - t0)} ms (${xs.length} VPC${xs.length === 1 ? "" : "s"})` }; } },
  { name: "Availability Zones", run: async () => { const zs = await ec2.describeAvailabilityZones(); const bad = zs.filter((z) => z.State !== "available"); return { ok: bad.length === 0, detail: `${zs.length - bad.length} of ${zs.length} available` }; } },
  { name: "VPCs and subnets", run: async () => { const [v, s] = await Promise.all([api.describeVpcs(), api.describeSubnets()]); const bad = [...v.filter((x) => x.State && x.State !== "available"), ...s.filter((x) => x.State && x.State !== "available")]; return { ok: bad.length === 0, detail: bad.length ? `${bad.length} resource(s) not available` : `${v.length} VPC(s) and ${s.length} subnet(s) available` }; } },
  { name: "NAT gateways", run: async () => { const xs = await api.describeNatGateways(); const bad = xs.filter((n) => (n.state || n.natGatewayState) === "failed"); return { ok: bad.length === 0, detail: bad.length ? `${bad.length} NAT gateway(s) failed` : `${xs.length} NAT gateway(s) checked, none failed` }; } },
  { name: "Network Firewall", run: async () => { const xs = await nf.listFirewalls(); const bad = xs.filter((f) => f.Status !== "READY" || f.Sync !== "IN_SYNC"); return { ok: bad.length === 0, detail: bad.length ? `${bad.length} firewall(s) not ready or out of sync` : `${xs.length} firewall(s) READY and IN_SYNC` }; } },
];

export default function VpcServiceHealth() {
  return <ServiceHealthPage title="Service health dashboard" service="Amazon VPC" probes={probes} />;
}
