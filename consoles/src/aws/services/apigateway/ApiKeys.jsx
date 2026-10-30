import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { fmtDate, ErrorAlert } from "../../kit/common.jsx";
import { navigate } from "../../../common/router.js";
import * as api from "./api.js";

function MaskedKey({ value }) {
  const [shown, setShown] = useState(false);
  return (
    <SpaceBetween direction="horizontal" size="xs">
      <Box variant="code">{shown ? value : "•".repeat(12)}</Box>
      <Button iconName={shown ? "eye" : "eye-off"} variant="icon" ariaLabel="Show/hide API key" onClick={() => setShown((v) => !v)} />
    </SpaceBetween>
  );
}

function AddToPlanModal({ keyId, visible, onDismiss }) {
  const notify = useNotify();
  const plans = useAsync(() => api.listUsagePlans(), []);
  const [plan, setPlan] = useState(null);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Add to usage plan"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" disabled={!plan} onClick={async () => { await api.createUsagePlanKey(plan.value, keyId); notify.success("Added to usage plan."); onDismiss(); }}>Add</Button>
      </SpaceBetween></Box>}>
      <FormField label="Usage plan"><Select selectedOption={plan} onChange={({ detail }) => setPlan(detail.selectedOption)} options={(plans.data || []).map((p) => ({ value: p.id, label: p.name }))} /></FormField>
    </Modal>
  );
}

export default function ApiKeys() {
  const notify = useNotify();
  const t = useAsync(() => api.listApiKeys(), []);
  const [sel, setSel] = useState([]);
  const [edit, setEdit] = useState(null);
  const [addToPlan, setAddToPlan] = useState(null);
  const [error, setError] = useState(null);

  return (
    <>
      {error && <Box padding={{ horizontal: "l", top: "s" }}><ErrorAlert error={error} /></Box>}
      <ResourceTable
        resourceName="API keys"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="id"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        empty={{ title: "No API keys", subtitle: "You don't have any API keys.", action: <Button onClick={() => navigate("apigateway", "create-api-key")}>Create API Key</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (k) => k.name },
          { id: "status", header: "Status", cell: (k) => <StatusIndicator type={k.enabled ? "success" : "stopped"}>{k.enabled ? "Active" : "Inactive"}</StatusIndicator> },
          { id: "id", header: "ID", cell: (k) => k.id },
          { id: "value", header: "API key", cell: (k) => <MaskedKey value={k.value} /> },
          { id: "description", header: "Description", cell: (k) => k.description || "-" },
          { id: "created", header: "Creation date", cell: (k) => fmtDate(k.createdDate) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown
              items={[
                { id: "edit", text: "Edit", disabled: sel.length !== 1 },
                { id: "delete", text: "Delete", disabled: !sel.length },
                { id: "import", text: "Import API keys" },
                { id: "addplan", text: "Add to usage plan", disabled: sel.length !== 1 },
              ]}
              onItemClick={async ({ detail }) => {
                try {
                  if (detail.id === "edit") setEdit(sel[0]);
                  else if (detail.id === "delete") { for (const k of sel) await api.deleteApiKey(k.id); notify.success("API key(s) deleted."); setSel([]); t.reload(); }
                  else if (detail.id === "import") notify.info("Importing API keys from OpenAPI/CSV isn't modeled by Vyomi.");
                  else if (detail.id === "addplan") setAddToPlan(sel[0].id);
                } catch (e) { setError(e); }
              }}
            >Actions</ButtonDropdown>
            <Button variant="primary" onClick={() => navigate("apigateway", "create-api-key")}>Create API key</Button>
          </SpaceBetween>
        }
      />
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header="Edit API key"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            await api.updateApiKey(edit.id, [{ op: "replace", path: "/description", value: edit.description }, { op: "replace", path: "/enabled", value: edit.enabled }]);
            notify.success("API key updated."); setEdit(null); t.reload();
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <SpaceBetween size="l">
          <FormField label="Description"><Input value={edit.description || ""} onChange={({ detail }) => setEdit({ ...edit, description: detail.value })} ariaLabel="Description" /></FormField>
        </SpaceBetween>}
      </Modal>
      <AddToPlanModal keyId={addToPlan} visible={!!addToPlan} onDismiss={() => setAddToPlan(null)} />
    </>
  );
}
