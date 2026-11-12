/* RDS capacity reservations: a reservation record (instance class, count, AZ, optional engine) with REAL utilisation matched against the
 * available DB instances. Create page = the console's single-page form. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import * as api from "../../kit/reservationsApi.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";

const NOTE = "Vyomi has no billing system: a reservation records the commitment. Utilisation is computed from the DB instances that are actually available (same class, and the same Availability Zone / engine when given).";

export function CapacityReservations() {
  const notify = useNotify();
  const t = useAsync(() => api.describeRdsReservations(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  return (
    <>
      <ResourceTable resourceName="Capacity reservations" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="ReservationId" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
        description={NOTE} filterPlaceholder="Find capacity reservations" empty={{ title: "No capacity reservations", description: "Create a reservation to hold instances of a class in an Availability Zone." }}
        columns={[{ id: "i", header: "Reservation ID", isRowHeader: true, sortingField: "ReservationId", cell: (r) => r.ReservationId }, { id: "n", header: "Name", cell: (r) => r.Name || "-" },
          { id: "s", header: "State", cell: (r) => <StatusIndicator type={r.State === "active" ? "success" : "stopped"}>{r.State}</StatusIndicator> },
          { id: "c", header: "Instance class", cell: (r) => r.DBInstanceClass }, { id: "az", header: "Availability Zone", cell: (r) => r.AvailabilityZone || "Any" },
          { id: "e", header: "Engine", cell: (r) => r.Engine || "Any" }, { id: "k", header: "Reserved", cell: (r) => r.InstanceCount },
          { id: "u", header: "In use", cell: (r) => `${r.UsedInstances} (${r.UtilizationPercent}%)` }, { id: "un", header: "Unused", cell: (r) => r.UnusedInstances },
          { id: "cr", header: "Created", cell: (r) => fmtDate(r.CreateTime) }]}
        actions={<SpaceBetween direction="horizontal" size="xs"><CapabilityBadge id="rds.capacity-reservations" />
          <Button disabled={!sel.length || sel[0].State === "cancelled"} onClick={() => setDel(true)}>Cancel reservation</Button>
          <Button variant="primary" onClick={() => navigate("rds", "create-capacity-reservation")}>Create capacity reservation</Button></SpaceBetween>} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="capacity reservation" names={sel.map((r) => r.ReservationId)} confirmText="cancel"
        onConfirm={async () => { await api.cancelRdsReservation(sel[0].ReservationId); notify.success("Cancelled the capacity reservation."); setSel([]); t.reload(); }} />
    </>
  );
}

export function CreateCapacityReservation() {
  const notify = useNotify();
  const [f, setF] = useState({ name: "", cls: "db.t3.micro", count: "1", az: "us-east-1a", engine: "", end: "" });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => ({ detail }) => setF({ ...f, [k]: detail.value });
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api.createRdsReservation({ DBInstanceClass: f.cls, InstanceCount: Number(f.count), ...(f.name ? { Name: f.name } : {}), ...(f.az ? { AvailabilityZone: f.az } : {}),
        ...(f.engine ? { Engine: f.engine } : {}), ...(f.end ? { EndDate: new Date(f.end).toISOString() } : {}) });
      notify.success(`Created capacity reservation ${r.ReservationId}.`);
      navigate("rds", "capacity-reservations");
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <ContentLayout header={<Header variant="h1" actions={<CapabilityBadge id="rds.capacity-reservations" />}>Create capacity reservation</Header>}>
      <Form actions={<SpaceBetween direction="horizontal" size="xs"><Button variant="link" href="#/rds/capacity-reservations" onFollow={follow}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Create capacity reservation</Button></SpaceBetween>}>
        <SpaceBetween size="l">
          <Alert type="info">{NOTE}</Alert>
          <ErrorAlert error={err} />
          <Container header={<Header variant="h2">Reservation settings</Header>}><SpaceBetween size="l">
            <FormField label="Name - optional"><Input ariaLabel="Name" value={f.name} onChange={set("name")} /></FormField>
            <FormField label="DB instance class"><Input ariaLabel="DB instance class" value={f.cls} onChange={set("cls")} /></FormField>
            <FormField label="Number of instances"><Input ariaLabel="Number of instances" inputMode="numeric" value={f.count} onChange={set("count")} /></FormField>
            <FormField label="Availability Zone - optional" description="Leave empty to match the class in any Availability Zone."><Input ariaLabel="Availability Zone" value={f.az} onChange={set("az")} /></FormField>
            <FormField label="Engine - optional" description="For example postgres or mysql."><Input ariaLabel="Engine" value={f.engine} onChange={set("engine")} /></FormField>
            <FormField label="End date - optional"><Input ariaLabel="End date" type="date" value={f.end} onChange={set("end")} /></FormField>
          </SpaceBetween></Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}
