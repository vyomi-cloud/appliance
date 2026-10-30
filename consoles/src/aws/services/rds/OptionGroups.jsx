import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

function CreateModal({ visible, onDismiss, onDone, notify }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [engine, setEngine] = useState("mysql");
  const [version, setVersion] = useState("8.0");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create option group"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name || !description} onClick={async () => {
          setBusy(true); setError(null);
          try { await api.createOptionGroup(name, description, engine, version); notify.success(`Option group "${name}" created.`); onDone(); onDismiss(); setName(""); setDescription(""); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>Create group</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
        <FormField label="Description"><Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" /></FormField>
        <FormField label="Engine"><Input value={engine} onChange={({ detail }) => setEngine(detail.value)} ariaLabel="Engine" /></FormField>
        <FormField label="Major engine version"><Input value={version} onChange={({ detail }) => setVersion(detail.value)} ariaLabel="Major engine version" /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function OptionGroups() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeOptionGroups());
  return (
    <>
      <ResourceTable
        resourceName="Option groups"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="OptionGroupName"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        empty={{ title: "No option groups found" }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (g) => g.OptionGroupName },
          { id: "desc", header: "Description", cell: (g) => g.OptionGroupDescription },
          { id: "engine", header: "Engine", cell: (g) => g.EngineName },
          { id: "version", header: "Engine version", cell: (g) => g.MajorEngineVersion },
          { id: "options", header: "Options", cell: () => "0" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1}>Add option</Button>
            <Button disabled={sel.length !== 1}>Modify option</Button>
            <Button disabled={sel.length !== 1}>Delete option</Button>
            <ButtonDropdown disabled={sel.length !== 1} items={[{ id: "delete-group", text: "Delete option group" }]} onItemClick={() => setDel(true)}>Delete option group</ButtonDropdown>
            <Button variant="primary" onClick={() => setCreate(true)}>Create group</Button>
          </SpaceBetween>
        }
      />
      <CreateModal visible={create} onDismiss={() => setCreate(false)} onDone={t.reload} notify={notify} />
      <DeleteModal visible={del} resourceType="option group" names={sel.map((g) => g.OptionGroupName)} onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const g of sel) await api.deleteOptionGroup(g.OptionGroupName); notify.success("Deleted."); setSel([]); t.reload(); }} />
    </>
  );
}
