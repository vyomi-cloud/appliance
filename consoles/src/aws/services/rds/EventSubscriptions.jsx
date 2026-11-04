import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const SOURCE_TYPES = ["db-instance", "db-snapshot", "db-parameter-group", "db-security-group"];

function CreateModal({ visible, onDismiss, onDone, notify }) {
  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  const [sourceType, setSourceType] = useState(SOURCE_TYPES[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create event subscription"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name || !topic} onClick={async () => {
          setBusy(true); setError(null);
          try { await api.createEventSubscription(name, topic, sourceType); notify.success(`Event subscription "${name}" created.`); onDone(); onDismiss(); setName(""); setTopic(""); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>Create</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
        <FormField label="SNS topic ARN"><Input value={topic} onChange={({ detail }) => setTopic(detail.value)} ariaLabel="SNS topic ARN" /></FormField>
        <FormField label="Source type">
          <Select selectedOption={{ value: sourceType, label: sourceType }} onChange={({ detail }) => setSourceType(detail.selectedOption.value)}
            options={SOURCE_TYPES.map((v) => ({ value: v, label: v }))} ariaLabel="Source type" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function EventSubscriptions() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeEventSubscriptions());
  return (
    <>
      <ResourceTable
        resourceName="Event subscriptions"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="CustSubscriptionId"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        empty={{ title: "No event subscription found", action: <Button onClick={() => setCreate(true)}>Create event subscription</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (e) => e.CustSubscriptionId },
          { id: "status", header: "Status", cell: (e) => e.Status },
          { id: "source", header: "Source Type", cell: (e) => e.SourceType },
          { id: "enabled", header: "Enabled", cell: (e) => (e.Enabled === "true" ? "Yes" : "No") },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1}>Edit</Button>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => setCreate(true)}>Create event subscription</Button>
          </SpaceBetween>
        }
      />
      <CreateModal visible={create} onDismiss={() => setCreate(false)} onDone={t.reload} notify={notify} />
      <DeleteModal visible={del} resourceType="event subscription" names={sel.map((e) => e.CustSubscriptionId)} onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const e of sel) await api.deleteEventSubscription(e.CustSubscriptionId); notify.success("Deleted."); setSel([]); t.reload(); }} />
    </>
  );
}
