/* Explore items: scan a table, create/edit items as JSON, delete items. */
import { useMemo, useState } from "react";
import Header from "@cloudscape-design/components/header";
import Table from "@cloudscape-design/components/table";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import Textarea from "@cloudscape-design/components/textarea";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Alert from "@cloudscape-design/components/alert";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { keyOf } from "./Tables.jsx";
import * as api from "./api.js";

export default function ExploreItems({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [edit, setEdit] = useState(null);      // {json, isNew}
  const [editErr, setEditErr] = useState(null);
  const [del, setDel] = useState(false);
  const meta = useAsync(() => api.describeTable(name), [name]);
  const scan = useAsync(() => api.scan(name, { limit: 50 }), [name]);
  const items = scan.data?.Items || [];
  const attrs = useMemo(() => {
    const keys = [keyOf(meta.data || {}, "HASH"), keyOf(meta.data || {}, "RANGE")].filter(Boolean);
    const rest = new Set();
    items.forEach((it) => Object.keys(it).forEach((k) => !keys.includes(k) && rest.add(k)));
    return [...keys, ...[...rest].sort()];
  }, [items, meta.data]);
  const keyAttrs = [keyOf(meta.data || {}, "HASH"), keyOf(meta.data || {}, "RANGE")].filter(Boolean);
  const keyFor = (it) => Object.fromEntries(keyAttrs.map((k) => [k, it[k]]));

  const save = async () => {
    setEditErr(null);
    try {
      const obj = JSON.parse(edit.json);
      await api.putItem(name, api.marshalItem(obj));
      notify.success(edit.isNew ? "The item has been saved successfully." : "The item has been updated successfully.");
      setEdit(null); scan.reload();
    } catch (e) { setEditErr(e); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Explore items: {name}</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2" description="Scan or query a table or index.">Scan or query items</Header>}>
          <SpaceBetween direction="horizontal" size="xs">
            <Select selectedOption={{ value: "scan", label: "Scan" }} options={[{ value: "scan", label: "Scan" }]} ariaLabel="Operation" />
            <Select selectedOption={{ value: name, label: `Table - ${name}` }} options={[{ value: name, label: `Table - ${name}` }]} ariaLabel="Table or index" />
            <Button variant="primary" onClick={scan.reload}>Run</Button>
          </SpaceBetween>
        </Container>
        <Alert type="success" statusIconAriaLabel="Success">
          Completed · Items returned: {items.length} · Items scanned: {scan.data?.ScannedCount ?? items.length}
        </Alert>
        <Table
          variant="container"
          items={items}
          loading={scan.loading}
          selectionType="multi"
          selectedItems={sel}
          onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
          trackBy={(it) => JSON.stringify(keyFor(it))}
          header={<Header variant="h2" counter={`(${items.length})`} actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button disabled={sel.length !== 1} onClick={() => setEdit({ json: JSON.stringify(api.unmarshalItem(sel[0]), null, 2), isNew: false })}>Edit item</Button>
              <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete items</Button>
              <Button variant="primary" onClick={() => setEdit({ json: JSON.stringify(Object.fromEntries(keyAttrs.map((k) => [k, ""])), null, 2), isNew: true })}>Create item</Button>
            </SpaceBetween>
          }>Table: {name} - Items returned</Header>}
          columnDefinitions={attrs.map((a) => ({ id: a, header: keyAttrs.includes(a) ? `${a} (${keyAttrs[0] === a ? "Partition key" : "Sort key"})` : a, cell: (it) => it[a] === undefined ? "" : fmt(api.unmarshal(it[a])) }))}
          empty={<Box textAlign="center" color="inherit"><b>The query did not return any results.</b></Box>}
        />
        {scan.error && <ErrorAlert error={scan.error} />}
      </SpaceBetween>
      <Modal visible={!!edit} size="large" onDismiss={() => setEdit(null)} header={edit?.isNew ? "Create item" : "Edit item"}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" onClick={save}>{edit?.isNew ? "Create item" : "Save changes"}</Button></SpaceBetween></Box>}>
        <FormField label="Attributes (JSON)" description="Plain JSON; strings, numbers, booleans, null, lists and maps are converted to DynamoDB types." errorText={editErr?.message}>
          <Textarea rows={16} value={edit?.json || ""} onChange={({ detail }) => setEdit({ ...edit, json: detail.value })} />
        </FormField>
      </Modal>
      <DeleteModal visible={del} resourceType="item" names={sel.map((it) => JSON.stringify(api.unmarshalItem(keyFor(it))))} confirmText="delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const it of sel) await api.deleteItem(name, keyFor(it)); notify.success(`${sel.length} item(s) deleted.`); setSel([]); scan.reload(); }} />
    </ContentLayout>
  );
}

const fmt = (v) => (v !== null && typeof v === "object" ? JSON.stringify(v) : String(v));
