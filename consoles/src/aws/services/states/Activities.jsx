import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { fmtDate, ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

function CreateActivityModal({ visible, onDismiss, onCreated }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true); setError(null);
    try { await api.createActivity(name); setName(""); onCreated(name); }
    catch (e) { setError(e); }
    finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create activity"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={submit}>Create activity</Button>
      </SpaceBetween></Box>}>
      <Form errorText={error && <ErrorAlert error={error} />}>
        <SpaceBetween size="m">
          <Header variant="h3">Activity details</Header>
          <FormField label="Activity name" constraintText="1 to 80 characters.">
            <Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Activity name" />
          </FormField>
        </SpaceBetween>
      </Form>
    </Modal>
  );
}

export default function Activities() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listActivities());

  return (
    <>
      <ResourceTable
        resourceName="Activities"
        items={data}
        trackBy="activityArn"
        loading={loading}
        error={error}
        onRefresh={reload}
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search activities"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (a) => <Link href={href("states", "activities", a.name)} onFollow={follow}>{a.name}</Link> },
          { id: "created", header: "Created", cell: (a) => fmtDate(a.creationDate) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => setCreate(true)}>Create activity</Button>
          </SpaceBetween>
        }
        empty={{ title: "No activities", subtitle: "Create an activity to get started.", action: <Button variant="primary" onClick={() => setCreate(true)}>Create activity</Button> }}
      />
      <CreateActivityModal visible={create} onDismiss={() => setCreate(false)}
        onCreated={(name) => { setCreate(false); notify.success(`Created activity "${name}".`); reload(); }} />
      <DeleteModal
        visible={del}
        resourceType="activity"
        names={sel.map((a) => a.name)}
        confirmText="delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => {
          for (const a of sel) await api.deleteActivity(a.activityArn);
          notify.success(`${sel.length} ${sel.length > 1 ? "activities" : "activity"} deleted.`);
          setSel([]); reload();
        }}
      />
    </>
  );
}
