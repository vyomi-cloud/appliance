/* EC2 dashboard: "Service health" (live probes of this environment's EC2 API and instance status checks, no invented incidents) and
 * "EC2 cost" (what the current inventory would cost on real AWS vs Vyomi's $0.00). Capability ids: ec2.dashboard.service-health,
 * ec2.dashboard.cost. */
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";
import * as vpcApi from "../vpc/api.js";
import { estimateCost, usd } from "./cost.js";

export function ServiceHealthWidget() {
  const t = useAsync(async () => {
    const t0 = performance.now();
    const zones = await api.describeAvailabilityZones();
    const apiMs = Math.round(performance.now() - t0);
    const status = await api.describeAllInstanceStatus().catch(() => null);
    return { zones, apiMs, status };
  }, []);
  const d = t.data;
  const bad = (d?.zones || []).filter((z) => z.State !== "available");
  const impaired = (d?.status || []).filter((s) => [s.instanceStatus?.status, s.systemStatus?.status].some((x) => x === "impaired"));
  const rows = d ? [
    ["Amazon EC2 API (us-east-1)", `DescribeAvailabilityZones answered in ${d.apiMs} ms`, true],
    ["Availability Zones", `${d.zones.length - bad.length} of ${d.zones.length} available`, bad.length === 0],
    ["Instance and system status checks", d.status ? (impaired.length ? `${impaired.length} instance(s) impaired: ${impaired.map((s) => s.instanceId).join(", ")}` : `${d.status.length} instance(s) checked, none impaired`) : "Status checks could not be read", d.status !== null && impaired.length === 0],
  ] : [];
  const ok = rows.every((r) => r[2]);
  return (
    <CapabilityContainer id="ec2.dashboard.service-health" title="Service health"
      actions={<Button iconName="refresh" ariaLabel="Refresh service health" onClick={t.reload} />}>
      {t.error ? <ErrorAlert error={t.error} /> : (
        <SpaceBetween size="s">
          <StatusIndicator type={!d ? "loading" : ok ? "success" : "warning"}>{!d ? "Checking" : ok ? "Service is operating normally" : "Some checks need attention"}</StatusIndicator>
          {rows.map(([name, detail, good]) => <div key={name}><Box variant="awsui-key-label">{name}</Box><StatusIndicator type={good ? "success" : "warning"}>{detail}</StatusIndicator></div>)}
        </SpaceBetween>)}
    </CapabilityContainer>
  );
}

export function CostWidget() {
  const t = useAsync(async () => {
    const [instances, volumes, addresses, snapshots, nats] = await Promise.all([
      api.describeInstances(), api.describeVolumes(), api.describeAddresses(), api.describeSnapshots(), vpcApi.describeNatGateways().catch(() => [])]);
    return estimateCost({ instances, volumes, addresses, snapshots, nats: nats.filter((n) => n.state !== "deleted" && n.natGatewayState !== "deleted") });
  }, []);
  const c = t.data;
  return (
    <CapabilityContainer id="ec2.dashboard.cost" title="EC2 cost"
      actions={<Button iconName="refresh" ariaLabel="Refresh cost" onClick={t.reload} />}>
      {t.error ? <ErrorAlert error={t.error} /> : !c ? <StatusIndicator type="loading">Calculating</StatusIndicator> : (
        <SpaceBetween size="m">
          <ColumnLayout columns={4} variant="text-grid">
            <div><Box variant="awsui-key-label">Charged by Vyomi</Box><Box variant="awsui-value-large" data-testid="cost-charged">$0.00</Box></div>
            <div><Box variant="awsui-key-label">Same resources on AWS, since launch</Box><Box variant="awsui-value-large" data-testid="cost-to-date">{usd(c.toDate)}</Box></div>
            <div><Box variant="awsui-key-label">Projected monthly on AWS</Box><Box variant="awsui-value-large" data-testid="cost-monthly">{usd(c.monthly)}</Box></div>
            <div><Box variant="awsui-key-label">Saved by running on Vyomi</Box><Box variant="awsui-value-large" color="text-status-success" data-testid="cost-saved">{usd(c.toDate)}</Box></div>
          </ColumnLayout>
          <Table variant="embedded" items={c.byType} trackBy="type" header={<Header variant="h3">Cost by resource type (AWS list prices)</Header>}
            columnDefinitions={[
              { id: "t", header: "Resource type", cell: (r) => r.type }, { id: "n", header: "Count", cell: (r) => r.count },
              { id: "m", header: "Projected monthly", cell: (r) => usd(r.monthly) }, { id: "d", header: "Since launch", cell: (r) => usd(r.toDate) },
            ]}
            empty={<Box textAlign="center" color="inherit">No billable EC2 resources.</Box>} />
          <Box variant="small" color="text-body-secondary">An estimate from this environment's current inventory at us-east-1 on-demand list prices (data transfer, taxes, discounts and free tier excluded). Vyomi never bills.</Box>
        </SpaceBetween>)}
    </CapabilityContainer>
  );
}
