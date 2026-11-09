/* EC2 UltraServers and Capacity Blocks - Dev Simplified page over core/ec2_ultraservers_core.py. No accelerator hardware exists:
 * offerings come from a fixed catalogue and blocks follow the clock (scheduled -> active -> expired). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import { awsRest } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

const us = (op, body = {}) => awsRest("vyomi-ultraservers", "POST", `/${op}`, { body });
const stat = (label, value) => <div><Box variant="awsui-key-label">{label}</Box><Box variant="awsui-value-large">{value}</Box></div>;
const stateType = (s) => (s === "active" ? "success" : s === "scheduled" ? "pending" : "stopped");

function Offerings({ types, onBought }) {
  const notify = useNotify();
  const opts = (types || []).map((t) => ({ value: t.type, label: t.kind === "ultraserver" ? `${t.type} (UltraServer, ${t.acceleratorsPerUnit}x ${t.accelerator})` : `${t.type} (${t.acceleratorsPerUnit}x ${t.accelerator})`, kind: t.kind }));
  const [type, setType] = useState(null);
  const [count, setCount] = useState("1");
  const [days, setDays] = useState("7");
  const [offers, setOffers] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const sel = type || opts[0];
  const search = async () => {
    setBusy(true); setError(null);
    try {
      const body = { CapacityDurationDays: Number(days) };
      body[sel.kind === "ultraserver" ? "UltraServerCount" : "InstanceCount"] = Number(count);
      body[sel.kind === "ultraserver" ? "UltraServerType" : "InstanceType"] = sel.value;
      setOffers((await us("DescribeCapacityBlockOfferings", body)).capacityBlockOfferings);
    } catch (e) { setError(e); setOffers(null); } finally { setBusy(false); }
  };
  const buy = async (o) => {
    try { await us("PurchaseCapacityBlock", { CapacityBlockOfferingId: o.capacityBlockOfferingId }); notify.success("Capacity block purchased (Dev Simplified: no hardware is reserved and nothing is billed)."); setOffers(null); onBought(); } catch (e) { notify.error(e); }
  };
  return (
    <Container header={<Header variant="h2" description="Search the Dev Simplified catalogue, then purchase an offering.">Find capacity block offerings</Header>}>
      <SpaceBetween size="m">
        {error && <ErrorAlert error={error} />}
        <ColumnLayout columns={4}>
          <FormField label="Instance or UltraServer type"><Select selectedOption={sel || null} options={opts} onChange={({ detail }) => setType(detail.selectedOption)} ariaLabel="Type" /></FormField>
          <FormField label={sel?.kind === "ultraserver" ? "UltraServer count" : "Instance count"}><Input type="number" value={count} onChange={({ detail }) => setCount(detail.value)} ariaLabel="Count" /></FormField>
          <FormField label="Duration (days)" constraintText="1-14 days, or a multiple of 7 up to 182"><Input type="number" value={days} onChange={({ detail }) => setDays(detail.value)} ariaLabel="Duration in days" /></FormField>
        </ColumnLayout>
        <Button variant="primary" loading={busy} onClick={search} disabled={!sel}>Find capacity blocks</Button>
        {offers && (
          <Table variant="embedded" items={offers} trackBy="capacityBlockOfferingId" empty={<Box textAlign="center">No offerings</Box>}
            columnDefinitions={[
              { id: "id", header: "Offering", cell: (o) => o.capacityBlockOfferingId, isRowHeader: true },
              { id: "az", header: "Availability Zone", cell: (o) => o.availabilityZone },
              { id: "s", header: "Start", cell: (o) => fmtDate(o.startDate) }, { id: "e", header: "End", cell: (o) => fmtDate(o.endDate) },
              { id: "f", header: "Upfront fee (illustrative)", cell: (o) => `$${o.upfrontFee}` },
              { id: "b", header: "", cell: (o) => <Button onClick={() => buy(o)}>Purchase</Button> },
            ]} />
        )}
      </SpaceBetween>
    </Container>
  );
}

export function UltraServers() {
  const notify = useNotify();
  const ov = useAsync(() => us("VyomiOverview"), []);
  const blocks = useAsync(async () => (await us("DescribeCapacityBlocks")).capacityBlocks, []);
  const servers = useAsync(async () => (await us("DescribeUltraServers")).ultraServers, []);
  const [sel, setSel] = useState([]);
  const reload = () => { ov.reload(); blocks.reload(); servers.reload(); setSel([]); };
  const one = sel[0];
  const act = async (op, body, ok) => { try { await us(op, body); notify.success(ok); reload(); } catch (e) { notify.error(e); } };
  const o = ov.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button iconName="refresh" ariaLabel="Refresh" onClick={reload} />}>UltraServers and Capacity Blocks</Header>}>
      <SpaceBetween size="l">
        <CapabilityContainer id="ec2.purchasing.ultraservers" title="Overview" description={o ? `As of ${o.asOf}` : ""}>
          <ColumnLayout columns={4} variant="text-grid">
            {stat("Scheduled blocks", o?.blocksByState?.scheduled ?? "-")}
            {stat("Active blocks", o?.blocksByState?.active ?? "-")}
            {stat("Active accelerators", o?.activeAccelerators ?? "-")}
            {stat("Active UltraServers", o?.activeUltraServers ?? "-")}
          </ColumnLayout>
        </CapabilityContainer>
        <Offerings types={o?.supportedTypes} onBought={reload} />
        <Table variant="container" items={blocks.data || []} loading={blocks.loading} trackBy="capacityBlockId" selectionType="single" selectedItems={sel}
          onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
          header={<Header variant="h2" counter={`(${(blocks.data || []).length})`} actions={<SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!one || one.state !== "active"} onClick={() => act("ExtendCapacityBlock", { CapacityBlockId: one.capacityBlockId, CapacityBlockExtensionDurationDays: 7 }, "Capacity block extended by 7 days.")}>Extend 7 days</Button>
            <Button disabled={!one || one.state !== "scheduled"} onClick={() => act("VyomiCancelCapacityBlock", { CapacityBlockId: one.capacityBlockId }, "Capacity block released.")}>Release (Vyomi)</Button></SpaceBetween>}>Capacity Blocks</Header>}
          columnDefinitions={[
            { id: "id", header: "Capacity Block ID", cell: (b) => b.capacityBlockId, isRowHeader: true },
            { id: "t", header: "Type", cell: (b) => b.ultraServerType || b.instanceType },
            { id: "n", header: "Units", cell: (b) => (b.ultraServerType ? `${b.ultraServerCount} UltraServer(s), ${b.instanceCount} hosts` : `${b.instanceCount} instance(s)`) },
            { id: "a", header: "Accelerators", cell: (b) => `${b.acceleratorCount} x ${b.acceleratorName}` },
            { id: "az", header: "Zone", cell: (b) => b.availabilityZone },
            { id: "s", header: "State", cell: (b) => <StatusIndicator type={stateType(b.state)}>{b.state}</StatusIndicator> },
            { id: "st", header: "Start", cell: (b) => fmtDate(b.startDate) }, { id: "e", header: "End", cell: (b) => fmtDate(b.endDate) },
            { id: "f", header: "Upfront fee (illustrative)", cell: (b) => `$${b.upfrontFee}` },
          ]}
          empty={<Box textAlign="center" color="inherit"><b>No capacity blocks</b><Box variant="p" color="inherit">Find an offering above to purchase one.</Box></Box>} />
        <Table variant="container" items={servers.data || []} loading={servers.loading} trackBy="ultraServerId"
          header={<Header variant="h2" counter={`(${(servers.data || []).length})`} description="One row per UltraServer domain bought as a capacity block.">UltraServers</Header>}
          columnDefinitions={[
            { id: "id", header: "UltraServer ID", cell: (x) => x.ultraServerId, isRowHeader: true },
            { id: "t", header: "Type", cell: (x) => x.ultraServerType },
            { id: "h", header: "Hosts", cell: (x) => `${x.hosts.filter((h) => h.status === "healthy").length} / ${x.hostCount} healthy` },
            { id: "a", header: "Accelerators", cell: (x) => `${x.acceleratorCount} x ${x.acceleratorName}` },
            { id: "s", header: "State", cell: (x) => <StatusIndicator type={stateType(x.state)}>{x.state}</StatusIndicator> },
            { id: "b", header: "Capacity Block", cell: (x) => x.capacityBlockId },
          ]}
          empty={<Box textAlign="center" color="inherit"><b>No UltraServers</b></Box>} />
      </SpaceBetween>
    </ContentLayout>
  );
}
