/* Code signing configurations — the resource (allowed signing profiles, validation
 * policy) is real, stored state; it is never enforced against a deployment. See
 * core/capabilities/aws/lambda.json (lambda.code-signing-configs / lambda.code-signing). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { fmtDate, ErrorAlert } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

const POLICIES = ["Warn", "Enforce"];

function CreateConfigModal({ visible, onDismiss, onCreated }) {
  const [description, setDescription] = useState("");
  const [profiles, setProfiles] = useState("");
  const [policy, setPolicy] = useState("Warn");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createCodeSigningConfig({
        Description: description,
        AllowedPublishers: { SigningProfileVersionArns: profiles.split(",").map((s) => s.trim()).filter(Boolean) },
        CodeSigningPolicies: { UntrustedArtifactOnDeployment: policy },
      });
      setDescription(""); setProfiles(""); setPolicy("Warn");
      onCreated();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create configuration"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={submit}>Create configuration</Button>
      </SpaceBetween></Box>}>
      <Form errorText={error && <ErrorAlert error={error} />}>
        <SpaceBetween size="l">
          <FormField label="Description"><Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" /></FormField>
          <FormField label="Signing profiles" description="Comma-separated signing profile version ARNs.">
            <Input value={profiles} onChange={({ detail }) => setProfiles(detail.value)} ariaLabel="Signing profiles" />
          </FormField>
          <FormField label="Signature validation policy">
            <Select selectedOption={{ value: policy, label: policy }} onChange={({ detail }) => setPolicy(detail.selectedOption.value)}
              options={POLICIES.map((p) => ({ value: p, label: p }))} />
          </FormField>
        </SpaceBetween>
      </Form>
    </Modal>
  );
}

export default function CodeSigningConfigurations() {
  const notify = useNotify();
  const t = useAsync(() => api.listCodeSigningConfigs(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);

  return (
    <>
      <ResourceTable
        resourceName="Code signing configurations"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="CodeSigningConfigId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search by attributes or search by keyword"
        empty={{ title: "There is no data to display.", action: <Button variant="primary" onClick={() => setCreate(true)}>Create configuration</Button> }}
        columns={[
          { id: "id", header: "ID", isRowHeader: true, cell: (c) => c.CodeSigningConfigId },
          { id: "desc", header: "Description", cell: (c) => c.Description || "-" },
          { id: "profiles", header: "Signing profiles", cell: (c) => (c.AllowedPublishers?.SigningProfileVersionArns || []).length },
          { id: "policy", header: "Signature validation policy", cell: (c) => c.CodeSigningPolicies?.UntrustedArtifactOnDeployment },
          { id: "modified", header: "Last modified", cell: (c) => fmtDate(c.LastModified) },
        ]}
        actions={
          <>
            <Button disabled={sel.length !== 1} onClick={() => setCreate(true)}>Edit</Button>
            {" "}
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            {" "}
            <Button variant="primary" onClick={() => setCreate(true)}>Create configuration</Button>
          </>
        }
      />
      <CreateConfigModal visible={create} onDismiss={() => setCreate(false)} onCreated={() => { setCreate(false); notify.success("Code signing configuration created."); t.reload(); }} />
      <DeleteModal visible={del} resourceType="code signing configuration" names={sel.map((c) => c.CodeSigningConfigId)}
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const c of sel) await api.deleteCodeSigningConfig(c.CodeSigningConfigId); notify.success(`${sel.length} configuration(s) deleted.`); setSel([]); t.reload(); }} />
    </>
  );
}
