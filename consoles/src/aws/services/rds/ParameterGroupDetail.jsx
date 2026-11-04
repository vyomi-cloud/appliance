import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Modal from "@cloudscape-design/components/modal";
import Input from "@cloudscape-design/components/input";
import FormField from "@cloudscape-design/components/form-field";
import Box from "@cloudscape-design/components/box";
import Spinner from "@cloudscape-design/components/spinner";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate, href, follow } from "../../../common/router.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

export default function ParameterGroupDetail({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [editing, setEditing] = useState(null);
  const [editValue, setEditValue] = useState("");
  const [del, setDel] = useState(false);
  const groups = useAsync(() => api.describeDBParameterGroups(), []);
  const t = useAsync(() => api.describeDBParameters(name), [name]);

  if (groups.loading || t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (groups.error) return <ErrorAlert error={groups.error} />;
  const g = (groups.data || []).find((x) => x.DBParameterGroupName === name);
  if (!g) return <Box textAlign="center" padding="xxl"><b>Parameter group not found</b></Box>;

  return (
    <ContentLayout header={
      <Header variant="h1" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <ButtonDropdown items={[{ id: "delete", text: "Delete" }]} onItemClick={() => setDel(true)}>Actions</ButtonDropdown>
          <Button disabled={sel.length !== 1} onClick={() => { setEditing(sel[0].ParameterName); setEditValue(sel[0].ParameterValue); }}>Edit</Button>
        </SpaceBetween>
      }>{name}</Header>
    }>
      <SpaceBetween size="l">
        <KeyValue title="Parameter group details" columns={3} items={[
          ["Name", g.DBParameterGroupName], ["Description", g.Description], ["Family", g.DBParameterGroupFamily],
          ["Type", g.Type || "DB Parameter Group"], ["ARN", g.DBParameterGroupArn],
        ]} />
        <ResourceTable
          resourceName="Parameters"
          items={t.data || []}
          loading={t.loading}
          onRefresh={t.reload}
          trackBy="ParameterName"
          selectionType="single"
          selectedItems={sel}
          onSelectionChange={setSel}
          filterPlaceholder="Filter parameters"
          columns={[
            { id: "name", header: "Name", isRowHeader: true, cell: (p) => p.ParameterName },
            { id: "value", header: "Value", cell: (p) => p.ParameterValue },
            { id: "allowed", header: "Allowed values", cell: (p) => p.AllowedValues || "-" },
            { id: "mod", header: "Modifiable", cell: (p) => (p.IsModifiable === "true" ? "Yes" : "No") },
            { id: "source", header: "Source", cell: (p) => p.Source },
            { id: "apply", header: "Apply type", cell: (p) => p.ApplyType },
            { id: "type", header: "Data type", cell: (p) => p.DataType },
            { id: "desc", header: "Description", cell: (p) => p.Description },
          ]}
        />
      </SpaceBetween>
      <Modal visible={!!editing} onDismiss={() => setEditing(null)} header={`Edit parameter: ${editing}`}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEditing(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            try {
              await api.modifyDBParameterGroup(name, [{ ParameterName: editing, ParameterValue: editValue }]);
              notify.success(`Parameter "${editing}" updated.`);
              t.reload();
            } catch (e) { notify.error(e); }
            setEditing(null);
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        <FormField label="Value"><Input value={editValue} onChange={({ detail }) => setEditValue(detail.value)} ariaLabel="Value" /></FormField>
      </Modal>
      <DeleteModal visible={del} resourceType="parameter group" names={[name]} onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deleteDBParameterGroup(name); notify.success(`Parameter group "${name}" deleted.`); navigate("rds", "parameter-groups"); }} />
    </ContentLayout>
  );
}
