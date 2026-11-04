/* StackSets — control plane only (core/capabilities/aws/cloudformation.json:
 * aws.cloudformation.stacksets): create/list/delete a StackSet's own template really
 * works; deploying stack instances across accounts/Regions is out of Vyomi's scope,
 * matching the spec's own note ("Out of Vyomi scope beyond listing"). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, NotSimulated } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

function CreateStackSetModal({ visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.createStackSet({ name, templateBody: template }); notify.success(`StackSet "${name}" created.`); onDone(); onDismiss(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create stack set" size="large"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!name || !template} onClick={submit}>Create stack set</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Stack set name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Stack set name" /></FormField>
        <FormField label="Template"><Textarea rows={10} value={template} onChange={({ detail }) => setTemplate(detail.value)} spellcheck={false} ariaLabel="Template" /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function StackSets() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listStackSets(), []);

  return (
    <SpaceBetween size="l">
      <ResourceTable
        resourceName="StackSets"
        items={data}
        trackBy="StackSetId"
        loading={loading}
        error={error}
        onRefresh={reload}
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find stack sets"
        columns={[
          { id: "n", header: "Stack set name", isRowHeader: true, cell: (s) => s.StackSetName },
          { id: "id", header: "Stack set ID", cell: (s) => s.StackSetId },
          { id: "pm", header: "Permission model", cell: (s) => s.PermissionModel },
          { id: "d", header: "Stack set description", cell: (s) => s.Description || "-" },
          { id: "drift", header: "Drift status", cell: () => "NOT_CHECKED" },
          { id: "dt", header: "Last drift check time", cell: () => "-" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={sel.length !== 1} items={[{ id: "delete", text: "Delete stack set" }]}
              onItemClick={async ({ detail }) => {
                if (detail.id === "delete") {
                  try { await api.deleteStackSet(sel[0].StackSetName); notify.success(`StackSet "${sel[0].StackSetName}" deleted.`); setSel([]); reload(); }
                  catch (e) { notify.error(e); }
                }
              }}>Actions</ButtonDropdown>
            <Button variant="primary" onClick={() => setCreate(true)}>Create stack set</Button>
          </SpaceBetween>
        }
        empty={{ title: "No stack sets to display", subtitle: "Create a stack set to get started.", action: <Button onClick={() => setCreate(true)}>Create stack set</Button> }}
      />
      <Container header={<Header variant="h2">Trusted access</Header>}>
        <NotSimulated feature="Trusted access with AWS Organizations" note="Service-managed permissions and multi-account/Region stack-instance deployment aren't modeled by Vyomi — a StackSet's own template is real, but it never deploys instances." />
      </Container>
      <CreateStackSetModal visible={create} onDismiss={() => setCreate(false)} onDone={reload} />
    </SpaceBetween>
  );
}
