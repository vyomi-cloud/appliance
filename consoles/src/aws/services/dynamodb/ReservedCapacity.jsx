/* DynamoDB reserved capacity: purchase records (1 or 3 year terms, multiples of 100 units) with REAL utilisation computed from the
 * provisioned RCU/WCU of every provisioned table and GSI. No billing - the console says so. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import ProgressBar from "@cloudscape-design/components/progress-bar";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import * as api from "../../kit/reservationsApi.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";

const TYPES = [{ value: "write", label: "Write capacity units" }, { value: "read", label: "Read capacity units" }];
const TERMS = [{ value: "1", label: "1 year" }, { value: "3", label: "3 years" }];

function Util({ label, u }) {
  return (
    <div>
      <Box variant="awsui-key-label">{label}</Box>
      {u.ReservedUnits ? <ProgressBar value={u.UtilizationPercent ?? 0} additionalInfo={`${u.UsedReservedUnits} of ${u.ReservedUnits} reserved units used`}
        description={`${u.UnusedReservedUnits} unused${u.UnreservedProvisionedUnits ? `, ${u.UnreservedProvisionedUnits} provisioned above the reservation (billed normally)` : ""}`} />
        : <Box color="text-body-secondary">Nothing reserved. {u.ProvisionedUnits} units provisioned.</Box>}
    </div>
  );
}

export default function ReservedCapacity() {
  const notify = useNotify();
  const t = useAsync(() => api.describeDdbReserved(), []);
  const [dlg, setDlg] = useState(false);
  const [f, setF] = useState({ type: TYPES[0], units: "100", term: TERMS[0] });
  const [err, setErr] = useState(null);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const buy = async () => {
    try { setErr(null); const r = await api.purchaseDdbReserved({ CapacityType: f.type.value, Units: Number(f.units), TermYears: Number(f.term.value) });
      notify.success(`Recorded reserved capacity ${r.ReservationId}.`); setDlg(false); t.reload(); } catch (e) { setErr(e); }
  };
  const u = t.data?.Utilization;
  return (
    <ContentLayout header={<Header variant="h1" description="Reserve read and write capacity units for 1 or 3 years." actions={<SpaceBetween direction="horizontal" size="xs"><CapabilityBadge id="dynamodb.account.reserved-capacity" />
      <Button variant="primary" onClick={() => { setErr(null); setDlg(true); }}>Purchase reserved capacity</Button></SpaceBetween>}>Reserved capacity</Header>}>
      <SpaceBetween size="l">
        <Alert type="info">Vyomi has no billing system: a purchase records the commitment. The utilisation below is computed from the throughput actually provisioned on your tables and global secondary indexes ({t.data?.ProvisionedTables ?? 0} provisioned tables).</Alert>
        {u && <Container header={<Header variant="h2">Utilization</Header>}><ColumnLayout columns={2}><Util label="Write capacity" u={u.write} /><Util label="Read capacity" u={u.read} /></ColumnLayout></Container>}
        <ResourceTable resourceName="Reservations" items={t.data?.Reservations || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="ReservationId" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
          empty={{ title: "No reserved capacity" }}
          columns={[{ id: "i", header: "Reservation ID", isRowHeader: true, cell: (r) => r.ReservationId }, { id: "t", header: "Type", cell: (r) => r.CapacityType }, { id: "u", header: "Units", cell: (r) => r.Units },
            { id: "te", header: "Term", cell: (r) => `${r.TermYears} year${r.TermYears > 1 ? "s" : ""}` }, { id: "s", header: "State", cell: (r) => <StatusIndicator type={r.State === "active" ? "success" : "stopped"}>{r.State}</StatusIndicator> },
            { id: "st", header: "Start", cell: (r) => fmtDate(r.StartTime) }, { id: "e", header: "End", cell: (r) => fmtDate(r.EndTime) }]}
          actions={<Button disabled={!sel.length} onClick={() => setDel(true)}>Remove record</Button>} />
      </SpaceBetween>
      <Modal visible={dlg} onDismiss={() => setDlg(false)} header="Purchase reserved capacity"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setDlg(false)}>Cancel</Button><Button variant="primary" onClick={buy}>Purchase</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m"><ErrorAlert error={err} />
          <FormField label="Capacity type"><Select selectedOption={f.type} options={TYPES} onChange={({ detail }) => setF({ ...f, type: detail.selectedOption })} /></FormField>
          <FormField label="Units" description="At least 100, in multiples of 100."><Input ariaLabel="Units" value={f.units} inputMode="numeric" onChange={({ detail }) => setF({ ...f, units: detail.value })} /></FormField>
          <FormField label="Term"><Select selectedOption={f.term} options={TERMS} onChange={({ detail }) => setF({ ...f, term: detail.selectedOption })} /></FormField></SpaceBetween>
      </Modal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="reservation record" names={sel.map((r) => r.ReservationId)}
        warning="Removes the simulated record only. A real purchase is non-refundable."
        onConfirm={async () => { await api.deleteDdbReserved(sel[0].ReservationId); notify.success("Removed the reservation record."); setSel([]); t.reload(); }} />
    </ContentLayout>
  );
}
