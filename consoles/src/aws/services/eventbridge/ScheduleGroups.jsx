import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate, Status } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

function CreateModal({ onDismiss, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await api.createScheduleGroup(name); notify.success(`Created schedule group ${name}.`); onDone(); onDismiss(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible onDismiss={onDismiss} header="Create schedule group"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!name} onClick={go}>Create schedule group</Button></SpaceBetween></Box>}>
      <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
    </Modal>
  );
}

export default function ScheduleGroups() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [creating, setCreating] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listScheduleGroups());

  const del = async () => {
    try { await api.deleteScheduleGroup(sel[0].Name); notify.success(`Deleted schedule group ${sel[0].Name}.`); setSel([]); reload(); }
    catch (e) { notify.error(e); }
  };

  return (
    <>
      <ResourceTable
        resourceName="Schedule groups"
        items={data}
        loading={loading}
        error={error}
        onRefresh={reload}
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        trackBy="Name"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (g) => g.Name },
          { id: "status", header: "Status", cell: (g) => <Status ok={g.State === "ACTIVE"}>{g.State}</Status> },
          { id: "created", header: "Created", cell: (g) => fmtDate(g.CreationDate) },
          { id: "modified", header: "Last modified", cell: (g) => fmtDate(g.CreationDate) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={del}>Delete</Button>
            <Button variant="primary" onClick={() => setCreating(true)}>Create schedule group</Button>
          </SpaceBetween>
        }
        empty={{ title: "No schedule groups", subtitle: "You don't have any schedule groups." }}
      />
      {creating && <CreateModal onDismiss={() => setCreating(false)} onDone={reload} />}
    </>
  );
}
