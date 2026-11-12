/* EC2 UltraServers page: Capacity Blocks that really reserve capacity from the instance pool (core/ec2_ultraservers_core.py;
 * RunInstances consumes the block's Capacity Reservation) plus an honest "Not in scope" panel for UltraServers (GPU hardware). */
import { useState } from "react";
import Badge from "@cloudscape-design/components/badge";
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
  const opts = (types || []).map((t) => ({ value: t.type, label: `${t.type} (${t.vcpu} vCPU, ${t.memoryMb} MB)` }));
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
      const body = { CapacityDurationDays: Number(days), InstanceCount: Number(count), InstanceType: sel.value };
      setOffers((await us("DescribeCapacityBlockOfferings", body)).capacityBlockOfferings);
    } catch (e) { setError(e); setOffers(null); } finally { setBusy(false); }
  };
  const buy = async (o) => {
    try { await us("PurchaseCapacityBlock", { CapacityBlockOfferingId: o.capacityBlockOfferingId }); notify.success("Capacity block purchased. Launch into it with its Capacity Reservation ID; nothing is billed."); setOffers(null); onBought(); } catch (e) { notify.error(e); }
  };
  return (
    <Container header={<Header variant="h2" description="Book instances from this environment's instance pool for a time window.">Find capacity block offerings</Header>}>
      <SpaceBetween size="m">
        {error && <ErrorAlert error={error} />}
        <ColumnLayout columns={4}>
          <FormField label="Instance type"><Select selectedOption={sel || null} options={opts} onChange={({ detail }) => setType(detail.selectedOption)} ariaLabel="Type" /></FormField>
          <FormField label="Instance count"><Input type="number" value={count} onChange={({ detail }) => setCount(detail.value)} ariaLabel="Count" /></FormField>
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
  const [sel, setSel] = useState([]);
  const reload = () => { ov.reload(); blocks.reload(); setSel([]); };
  const one = sel[0];
  const act = async (op, body, ok) => { try { await us(op, body); notify.success(ok); reload(); } catch (e) { notify.error(e); } };
  const o = ov.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button iconName="refresh" ariaLabel="Refresh" onClick={reload} />}>UltraServers</Header>}>
      <SpaceBetween size="l">
        <CapabilityContainer id="ec2.purchasing.capacity-blocks" title="Capacity Blocks" description={o ? `Instance pool ${o.poolMb} MB, ${o.bookedMb} MB booked (${o.asOf})` : ""}>
          <ColumnLayout columns={4} variant="text-grid">
            {stat("Scheduled blocks", o?.blocksByState?.scheduled ?? "-")}
            {stat("Active blocks", o?.blocksByState?.active ?? "-")}
            {stat("Expired blocks", o?.blocksByState?.expired ?? "-")}
            {stat("Pool booked", o ? `${Math.round((100 * o.bookedMb) / Math.max(o.poolMb, 1))}%` : "-")}
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
            { id: "t", header: "Instance type", cell: (b) => b.instanceType },
            { id: "n", header: "Instances", cell: (b) => b.instanceCount },
            { id: "r", header: "Reservation (launch target)", cell: (b) => b.capacityReservationId },
            { id: "az", header: "Zone", cell: (b) => b.availabilityZone },
            { id: "s", header: "State", cell: (b) => <StatusIndicator type={stateType(b.state)}>{b.state}</StatusIndicator> },
            { id: "st", header: "Start", cell: (b) => fmtDate(b.startDate) }, { id: "e", header: "End", cell: (b) => fmtDate(b.endDate) },
            { id: "f", header: "Upfront fee (illustrative)", cell: (b) => `$${b.upfrontFee}` },
          ]}
          empty={<Box textAlign="center" color="inherit"><b>No capacity blocks</b><Box variant="p" color="inherit">Find an offering above to purchase one.</Box></Box>} />
        <Container header={<Header variant="h2">UltraServers</Header>}>
          <div data-vyomi-not-in-scope="ec2.purchasing.ultraservers">
            <SpaceBetween size="xs">
              <Badge color="grey">Not in scope</Badge>
              <Box variant="p">UltraServers (multi-host GPU and Trainium domains) are physical hardware in AWS data centres, so Vyomi does not offer them; use Capacity Blocks above, which book real capacity for the instance types Vyomi runs.</Box>
            </SpaceBetween>
          </div>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
