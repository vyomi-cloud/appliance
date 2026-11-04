/* EC2 Savings Plans and Capacity Manager - real pages over core/savingsplans_core.py (the savingsplans API plus two Vyomi views derived
 * from the running EC2 inventory). UltraServers stays a registered gap (no accelerator capacity to manage). */
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

const sp = (op, body = {}) => awsRest("savingsplans", "POST", `/${op}`, { body });
const money = (n, d = 4) => `$${Number(n || 0).toFixed(d)}`;
const pct = (n) => `${Number(n || 0).toFixed(1)}%`;
const stat = (label, value) => <div><Box variant="awsui-key-label">{label}</Box><Box variant="awsui-value-large">{value}</Box></div>;

const TYPES = [{ value: "Compute", label: "Compute Savings Plans" }, { value: "EC2Instance", label: "EC2 Instance Savings Plans" }];
const TERMS = [{ value: "31536000", label: "1 year" }, { value: "94608000", label: "3 year" }];
const PAYS = ["All Upfront", "Partial Upfront", "No Upfront"].map((v) => ({ value: v, label: v }));

function Purchase({ onDone }) {
  const notify = useNotify();
  const [f, setF] = useState({ type: TYPES[0], term: TERMS[0], pay: PAYS[2], family: "m5", commitment: "0.10" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const buy = async () => {
    setBusy(true); setError(null);
    try {
      const o = await sp("DescribeSavingsPlansOfferings", { planTypes: [f.type.value], paymentOptions: [f.pay.value], durations: [Number(f.term.value)],
        ...(f.type.value === "EC2Instance" ? { filters: [{ name: "instanceFamily", values: [f.family.trim()] }] } : {}) });
      const off = o.searchResults?.[0];
      if (!off) throw new Error("No offering matches these choices (check the instance family).");
      const hours = Number(f.term.value) / 3600, c = Number(f.commitment);
      const upfront = f.pay.value === "All Upfront" ? c * hours : f.pay.value === "Partial Upfront" ? c * hours / 2 : 0;
      await sp("CreateSavingsPlan", { savingsPlanOfferingId: off.offeringId, commitment: f.commitment, ...(upfront ? { upfrontPaymentAmount: upfront.toFixed(2) } : {}) });
      notify.success("Savings Plan purchased. Vyomi does not bill - the plan only affects the coverage figures.");
      onDone();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const set = (k) => ({ detail }) => setF((p) => ({ ...p, [k]: detail.selectedOption || detail.value }));
  return (
    <Container header={<Header variant="h2" description="Pick a plan type, term and an hourly commitment (USD).">Purchase Savings Plans</Header>}>
      <SpaceBetween size="m">
        {error && <ErrorAlert error={error} />}
        <ColumnLayout columns={3}>
          <FormField label="Savings Plans type"><Select selectedOption={f.type} options={TYPES} onChange={set("type")} ariaLabel="Savings Plans type" /></FormField>
          <FormField label="Term"><Select selectedOption={f.term} options={TERMS} onChange={set("term")} ariaLabel="Term" /></FormField>
          <FormField label="Payment option"><Select selectedOption={f.pay} options={PAYS} onChange={set("pay")} ariaLabel="Payment option" /></FormField>
          {f.type.value === "EC2Instance" && <FormField label="Instance family"><Input value={f.family} onChange={set("family")} ariaLabel="Instance family" /></FormField>}
          <FormField label="Hourly commitment (USD)"><Input type="number" value={f.commitment} onChange={set("commitment")} ariaLabel="Hourly commitment" /></FormField>
        </ColumnLayout>
        <Button variant="primary" loading={busy} onClick={buy}>Add to cart and purchase</Button>
      </SpaceBetween>
    </Container>
  );
}

export function SavingsPlans() {
  const notify = useNotify();
  const plans = useAsync(async () => (await sp("DescribeSavingsPlans")).savingsPlans || [], []);
  const cov = useAsync(() => sp("VyomiCoverage"), []);
  const [sel, setSel] = useState([]);
  const reload = () => { plans.reload(); cov.reload(); setSel([]); };
  const one = sel[0];
  const act = async (op, ok) => { try { await sp(op, { savingsPlanId: one.savingsPlanId }); notify.success(ok); reload(); } catch (e) { notify.error(e); } };
  const c = cov.data;
  return (
    <ContentLayout header={<Header variant="h1">Savings Plans</Header>}>
      <SpaceBetween size="l">
        <CapabilityContainer id="ec2.purchasing.savings-plans" title="Coverage and utilization" description={c ? `Current hourly run-rate of the running EC2 instances (${c.asOf}).` : ""}>
          <ColumnLayout columns={4} variant="text-grid">
            {stat("Coverage", pct(c?.coveragePercentage))}
            {stat("Utilization", pct(c?.utilizationPercentage))}
            {stat("Hourly commitment", money(c?.totalCommitmentPerHour))}
            {stat("Unused commitment / hr", money(c?.unusedCommitmentPerHour))}
            {stat("On-demand cost / hr", money(c?.onDemandCostPerHour))}
            {stat("Covered by plans / hr", money(c?.coveredOnDemandPerHour))}
            {stat("Uncovered / hr", money(c?.uncoveredOnDemandPerHour))}
            {stat("Net savings / hr", money(c?.netSavingsPerHour))}
          </ColumnLayout>
        </CapabilityContainer>
        <Purchase onDone={reload} />
        <Table variant="container" items={plans.data || []} loading={plans.loading} trackBy="savingsPlanId" selectionType="single" selectedItems={sel}
          onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
          header={<Header variant="h2" counter={`(${(plans.data || []).length})`} actions={<SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!one || one.state !== "queued"} onClick={() => act("DeleteQueuedSavingsPlan", "Queued Savings Plan deleted.")}>Delete queued plan</Button>
            <Button disabled={!one || one.state !== "active"} onClick={() => act("ReturnSavingsPlan", "Savings Plan returned.")}>Return plan</Button></SpaceBetween>}>Inventory</Header>}
          columnDefinitions={[
            { id: "id", header: "Savings Plan ID", cell: (p) => p.savingsPlanId }, { id: "t", header: "Type", cell: (p) => p.savingsPlanType + (p.ec2InstanceFamily ? ` (${p.ec2InstanceFamily})` : "") },
            { id: "c", header: "Hourly commitment", cell: (p) => money(p.commitment, 3) }, { id: "pay", header: "Payment", cell: (p) => p.paymentOption },
            { id: "term", header: "Term", cell: (p) => (p.termDurationInSeconds === 31536000 ? "1 year" : "3 year") },
            { id: "s", header: "State", cell: (p) => <StatusIndicator type={p.state === "active" ? "success" : p.state === "queued" ? "pending" : "stopped"}>{p.state}</StatusIndicator> },
            { id: "st", header: "Start", cell: (p) => fmtDate(p.start) }, { id: "e", header: "End", cell: (p) => fmtDate(p.end) },
          ]}
          empty={<Box textAlign="center" color="inherit"><b>No Savings Plans</b></Box>} />
        <Table variant="container" items={c?.instances || []} loading={cov.loading} header={<Header variant="h2" counter={`(${(c?.instances || []).length})`}>Running instances and their on-demand cost</Header>}
          columnDefinitions={[{ id: "i", header: "Instance", cell: (i) => i.id }, { id: "t", header: "Type", cell: (i) => i.type }, { id: "a", header: "Zone", cell: (i) => i.az },
            { id: "o", header: "On-demand / hr", cell: (i) => money(i.onDemandPerHour) }, { id: "u", header: "Uncovered / hr", cell: (i) => money(i.uncoveredPerHour) }]}
          empty={<Box textAlign="center" color="inherit">No running instances</Box>} />
      </SpaceBetween>
    </ContentLayout>
  );
}

export function CapacityManager() {
  const ov = useAsync(() => sp("VyomiCapacityOverview"), []);
  const d = ov.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button iconName="refresh" onClick={ov.reload} ariaLabel="Refresh" />}>Capacity Manager</Header>}>
      <SpaceBetween size="l">
        {ov.error && <ErrorAlert error={ov.error} />}
        <CapabilityContainer id="ec2.purchasing.capacity-manager" title="Capacity summary" description={d ? `Derived from the simulator's EC2 inventory (${d.asOf}).` : ""}>
          <ColumnLayout columns={4} variant="text-grid">
            {stat("Running instances", d?.runningInstances ?? "-")}
            {stat("Running vCPUs", d?.runningVcpus ?? "-")}
            {stat("Stopped instances", d?.stoppedInstances ?? "-")}
            {stat("Spot requests", d?.spotRequests ?? "-")}
            {stat("Active Reserved Instances", d?.reservedInstances?.active ?? "-")}
            {stat("Unused Reserved Instances", d?.reservedInstances?.unused ?? "-")}
            {stat("Capacity Reservations", d?.capacityReservations ?? "-")}
            {stat("Savings Plans coverage", pct(d?.savingsPlans?.coveragePercentage))}
          </ColumnLayout>
        </CapabilityContainer>
        <Table variant="container" items={d?.byInstanceType || []} loading={ov.loading} header={<Header variant="h2">Usage by instance type</Header>}
          columnDefinitions={[{ id: "t", header: "Instance type", cell: (r) => r.instanceType }, { id: "r", header: "Running", cell: (r) => r.running }, { id: "v", header: "vCPUs", cell: (r) => r.vcpus },
            { id: "s", header: "Spot", cell: (r) => r.spot }, { id: "ri", header: "Reserved Instances", cell: (r) => r.reservedInstances }, { id: "cr", header: "Capacity reserved", cell: (r) => r.capacityReservations }]}
          empty={<Box textAlign="center" color="inherit">No instances</Box>} />
        <Table variant="container" items={d?.byAvailabilityZone || []} loading={ov.loading} header={<Header variant="h2">Usage by Availability Zone</Header>}
          columnDefinitions={[{ id: "a", header: "Availability Zone", cell: (r) => r.availabilityZone }, { id: "r", header: "Running", cell: (r) => r.running }, { id: "v", header: "vCPUs", cell: (r) => r.vcpus }]}
          empty={<Box textAlign="center" color="inherit">No instances</Box>} />
      </SpaceBetween>
    </ContentLayout>
  );
}
