/* Maintenance window detail — Details + Targets. Real GetMaintenanceWindow,
 * RegisterTargetWithMaintenanceWindow/DescribeMaintenanceWindowTargets. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Spinner from "@cloudscape-design/components/spinner";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, fmtDate, KeyValue } from "../../kit/common.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

function TargetsTab({ windowId }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeWindowTargets(windowId), [windowId]);
  const [sel, setSel] = useState([]);
  const [register, setRegister] = useState(false);
  const [instanceIds, setInstanceIds] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Table variant="container" items={t.data || []} loading={t.loading} trackBy="WindowTargetId"
      selectionType="multi" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
      header={<Header variant="h2" counter={`(${(t.data || []).length})`} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!sel.length} onClick={async () => { for (const x of sel) await api.deregisterWindowTarget(windowId, x.WindowTargetId); notify.success("Target(s) deregistered."); setSel([]); t.reload(); }}>Deregister target</Button>
          <Button variant="primary" onClick={() => setRegister(true)}>Register target</Button>
        </SpaceBetween>
      }>Targets</Header>}
      columnDefinitions={[
        { id: "id", header: "Target ID", cell: (x) => x.WindowTargetId },
        { id: "type", header: "Resource type", cell: (x) => x.ResourceType },
        { id: "targets", header: "Targets", cell: (x) => (x.Targets || []).map((v) => (v.Values || []).join(", ")).join("; ") },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No targets</b></Box>}>
      <Modal visible={register} onDismiss={() => setRegister(false)} header="Register target"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setRegister(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!instanceIds.trim()} onClick={async () => {
            setBusy(true);
            try {
              const ids = instanceIds.split(",").map((s) => s.trim()).filter(Boolean);
              await api.registerWindowTarget(windowId, { ResourceType: "INSTANCE", Targets: [{ Key: "InstanceIds", Values: ids }] });
              notify.success("Target registered."); setInstanceIds(""); setRegister(false); t.reload();
            } catch (e) { notify.error(e); } finally { setBusy(false); }
          }}>Register target</Button>
        </SpaceBetween></Box>}>
        <FormField label="Instance IDs" constraintText="Comma-separated.">
          <Input value={instanceIds} placeholder="i-0123456789abcdef0" onChange={({ detail }) => setInstanceIds(detail.value)} ariaLabel="Instance IDs" />
        </FormField>
      </Modal>
    </Table>
  );
}

export default function MaintenanceWindowDetail({ params }) {
  const windowId = params.id;
  const notify = useNotify();
  const d = useAsync(() => api.getMaintenanceWindow(windowId), [windowId]);
  const [delModal, setDelModal] = useState(false);
  if (d.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const w = d.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={async () => { await api.updateMaintenanceWindow(windowId, { Enabled: !w.Enabled }); notify.success(`Maintenance window ${w.Enabled ? "disabled" : "enabled"}.`); d.reload(); }}>{w.Enabled ? "Disable" : "Enable"}</Button>
        <Button onClick={() => setDelModal(true)}>Delete</Button>
      </SpaceBetween>
    }>{w.Name}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Maintenance window details" columns={4} items={[
          ["Maintenance window ID", w.WindowId], ["Enabled", <StatusIndicator key="e" type={w.Enabled ? "success" : "stopped"}>{w.Enabled ? "Enabled" : "Disabled"}</StatusIndicator>],
          ["Schedule", w.Schedule], ["Schedule timezone", w.ScheduleTimezone], ["Duration", `${w.Duration} hours`],
          ["Cutoff", `${w.Cutoff} hours`], ["Allow unassociated targets", w.AllowUnassociatedTargets ? "Yes" : "No"], ["Next execution", fmtDate(w.NextExecutionTime)],
        ]} />
        <Tabs tabs={[{ id: "targets", label: "Targets", content: <TargetsTab windowId={windowId} /> }]} />
      </SpaceBetween>
      <DeleteModal visible={delModal} onDismiss={() => setDelModal(false)} resourceType="maintenance window" names={[w.Name]}
        onConfirm={async () => { await api.deleteMaintenanceWindow(windowId); navigate("ssm", "maintenance-windows"); }} />
    </ContentLayout>
  );
}
