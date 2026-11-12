import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { navigate } from "../../../common/router.js";
import * as api from "./api.js";

export default function UsagePlans() {
  const notify = useNotify();
  const t = useAsync(() => api.listUsagePlans(), []);
  const [sel, setSel] = useState([]);
  const [edit, setEdit] = useState(null);
  const [error, setError] = useState(null);

  return (
    <>
      {error && <Box padding={{ horizontal: "l", top: "s" }}><ErrorAlert error={error} /></Box>}
      <ResourceTable
        resourceName="Usage plans"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="id"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        empty={{ title: "No usage plans found", action: <Button onClick={() => navigate("apigateway", "create-usage-plan")}>Create usage plan</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (p) => p.name },
          { id: "id", header: "ID", cell: (p) => p.id },
          { id: "rate", header: "Request rate", cell: (p) => p.throttle?.rateLimit ?? "-" },
          { id: "burst", header: "Burst", cell: (p) => p.throttle?.burstLimit ?? "-" },
          { id: "quota", header: "Quota", cell: (p) => (p.quota?.limit ? `${p.quota.limit} / ${(p.quota.period || "").toLowerCase()}` : "-") },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => setEdit(sel[0])}>Edit</Button>
            <Button disabled={!sel.length} onClick={async () => { for (const p of sel) await api.deleteUsagePlan(p.id); notify.success("Usage plan(s) deleted."); setSel([]); t.reload(); }}>Delete</Button>
            <Button variant="primary" onClick={() => navigate("apigateway", "create-usage-plan")}>Create usage plan</Button>
          </SpaceBetween>
        }
      />
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header="Edit usage plan"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            try {
              await api.updateUsagePlan(edit.id, [{ op: "replace", path: "/name", value: edit.name }, { op: "replace", path: "/description", value: edit.description }]);
              notify.success("Usage plan updated."); setEdit(null); t.reload();
            } catch (e) { setError(e); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <SpaceBetween size="l">
          <FormField label="Name"><Input value={edit.name} onChange={({ detail }) => setEdit({ ...edit, name: detail.value })} ariaLabel="Name" /></FormField>
          <FormField label="Description"><Input value={edit.description || ""} onChange={({ detail }) => setEdit({ ...edit, description: detail.value })} ariaLabel="Description" /></FormField>
        </SpaceBetween>}
      </Modal>
    </>
  );
}
