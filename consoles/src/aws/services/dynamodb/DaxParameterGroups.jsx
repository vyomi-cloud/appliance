import { useEffect, useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

function CreateParameterGroupModal({ visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [itemTtl, setItemTtl] = useState("5");
  const [queryTtl, setQueryTtl] = useState("5");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createDaxParameterGroup({ ParameterGroupName: name, Description: description });
      await api.updateDaxParameterGroup(name, [
        { ParameterName: "record-ttl-millis", ParameterValue: String(Math.max(0, Number(itemTtl) || 0) * 60000) },
        { ParameterName: "query-ttl-millis", ParameterValue: String(Math.max(0, Number(queryTtl) || 0) * 60000) },
      ]);
      notify.success(`Parameter group "${name}" created.`);
      onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create parameter group"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name} onClick={submit}>Create parameter group</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Group name">
          <Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Group name" />
        </FormField>
        <FormField label="Group description" description="optional">
          <Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Group description" />
        </FormField>
        <FormField label="Item Time to Live (TTL)" constraintText="minutes">
          <Input type="number" value={itemTtl} onChange={({ detail }) => setItemTtl(detail.value)} ariaLabel="Item Time to Live (TTL)" />
        </FormField>
        <FormField label="Query Time to Live (TTL)" constraintText="minutes">
          <Input type="number" value={queryTtl} onChange={({ detail }) => setQueryTtl(detail.value)} ariaLabel="Query Time to Live (TTL)" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function EditParameterGroupModal({ group, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const params = useAsync(() => (visible && group ? api.describeDaxParameters(group.ParameterGroupName) : Promise.resolve([])), [visible, group?.ParameterGroupName]);
  const [recordTtl, setRecordTtl] = useState("0");
  const [queryTtl, setQueryTtl] = useState("300000");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!params.data?.length) return;
    const r = params.data.find((p) => p.ParameterName === "record-ttl-millis");
    const q = params.data.find((p) => p.ParameterName === "query-ttl-millis");
    if (r) setRecordTtl(r.ParameterValue);
    if (q) setQueryTtl(q.ParameterValue);
  }, [params.data]);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.updateDaxParameterGroup(group.ParameterGroupName, [
        { ParameterName: "record-ttl-millis", ParameterValue: recordTtl },
        { ParameterName: "query-ttl-millis", ParameterValue: queryTtl },
      ]);
      notify.success(`Parameter group "${group.ParameterGroupName}" updated.`);
      onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} onDismiss={onDismiss} header={`Edit parameters: ${group?.ParameterGroupName || ""}`}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={submit}>Save changes</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Item Time to Live (TTL)" description="record-ttl-millis — milliseconds before an item cache entry expires (0 = never).">
          <Input type="number" value={recordTtl} onChange={({ detail }) => setRecordTtl(detail.value)} ariaLabel="Item Time to Live (TTL)" />
        </FormField>
        <FormField label="Query Time to Live (TTL)" description="query-ttl-millis — milliseconds before a query cache entry expires.">
          <Input type="number" value={queryTtl} onChange={({ detail }) => setQueryTtl(detail.value)} ariaLabel="Query Time to Live (TTL)" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function DaxParameterGroups() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [edit, setEdit] = useState(false);
  const [del, setDel] = useState(false);
  const groups = useAsync(() => api.describeDaxParameterGroups(), []);
  const ttlByGroup = useAsync(async () => {
    const rows = await Promise.all((groups.data || []).map((g) => api.describeDaxParameters(g.ParameterGroupName)));
    return Object.fromEntries((groups.data || []).map((g, i) => [g.ParameterGroupName, rows[i]]));
  }, [groups.data]);

  const ttl = (name, param) => ttlByGroup.data?.[name]?.find((p) => p.ParameterName === param)?.ParameterValue ?? "-";

  return (
    <ContentLayout header={<Header variant="h1" actions={<CapabilityBadge id="dynamodb.dax.parameter-groups" />}>Parameter groups</Header>}>
      <ResourceTable
        resourceName="Parameter groups"
        items={groups.data || []}
        loading={groups.loading}
        error={groups.error}
        onRefresh={groups.reload}
        trackBy="ParameterGroupName"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (g) => g.ParameterGroupName },
          { id: "desc", header: "Description", cell: (g) => g.Description || "-" },
          { id: "item-ttl", header: "Item Time to Live (TTL)", cell: (g) => `${ttl(g.ParameterGroupName, "record-ttl-millis")} ms` },
          { id: "query-ttl", header: "Query Time to Live (TTL)", cell: (g) => `${ttl(g.ParameterGroupName, "query-ttl-millis")} ms` },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => setEdit(true)}>Edit</Button>
            <Button disabled={!sel.length || sel.some((g) => g.ParameterGroupName === "default.dax1.0")} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => setCreate(true)}>Create parameter group</Button>
          </SpaceBetween>
        }
        empty={{ title: "No parameter groups", subtitle: "You have not created any DAX parameter groups yet.", action: <Button onClick={() => setCreate(true)}>Create parameter group</Button> }}
      />
      <CreateParameterGroupModal visible={create} onDismiss={() => setCreate(false)} onDone={groups.reload} />
      <EditParameterGroupModal group={edit ? sel[0] : null} visible={edit} onDismiss={() => setEdit(false)}
        onDone={() => { groups.reload(); ttlByGroup.reload(); }} />
      <DeleteModal visible={del} resourceType="parameter group" names={sel.map((g) => g.ParameterGroupName)}
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const g of sel) await api.deleteDaxParameterGroup(g.ParameterGroupName); notify.success(`${sel.length} parameter group(s) deleted.`); setSel([]); groups.reload(); }} />
    </ContentLayout>
  );
}
