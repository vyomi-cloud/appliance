/* Policy detail — Summary + Permissions / Entities attached / Policy versions /
 * Last Accessed tabs. "Summary" view renders the pretty-printed JSON (a real per-service
 * access-level breakdown isn't computed; we don't fake one). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Toggle from "@cloudscape-design/components/toggle";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

function PermissionsTab({ policy }) {
  const [view, setView] = useState("Summary");
  const [showRemaining, setShowRemaining] = useState(false);
  const doc = policy.Document ?? policy.document;
  return (
    <Container header={<Header variant="h2">Permissions defined in this policy</Header>}>
      <SpaceBetween size="m">
        <FormField label="View">
          <RadioGroup value={view} onChange={({ detail }) => setView(detail.value)} items={[{ value: "Summary", label: "Summary" }, { value: "JSON", label: "JSON" }]} />
        </FormField>
        {view === "Summary" ? (
          <>
            <Toggle checked={showRemaining} onChange={({ detail }) => setShowRemaining(detail.checked)}>Show remaining services</Toggle>
            <FormField label="Allow" description="A real per-service access-level breakdown isn't computed; the policy document is rendered instead.">
              <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(doc, null, 2)}</pre></Box>
            </FormField>
          </>
        ) : (
          <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(doc, null, 2)}</pre></Box>
        )}
      </SpaceBetween>
    </Container>
  );
}

function EntitiesTab({ policyArn }) {
  const notify = useNotify();
  const e = useAsync(() => api.listEntitiesForPolicy(policyArn), [policyArn]);
  if (e.loading) return <Spinner />;
  const rows = [
    ...e.data.users.map((u) => ({ name: u.UserName, type: "User" })),
    ...e.data.groups.map((g) => ({ name: g.GroupName, type: "Group" })),
    ...e.data.roles.map((r) => ({ name: r.RoleName, type: "Role" })),
  ];
  const boundaryRows = [
    ...e.data.boundaryUsers.map((u) => ({ name: u.UserName, type: "User" })),
    ...e.data.boundaryRoles.map((r) => ({ name: r.RoleName, type: "Role" })),
  ];
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="iam.policy.entities-attached" title="Attached as a permissions policy" counter={`(${rows.length})`}>
        <Table variant="embedded" items={rows} columnDefinitions={[{ id: "name", header: "Entity name", cell: (r) => r.name }, { id: "type", header: "Entity type", cell: (r) => r.type }]}
          empty={<Box textAlign="center" color="inherit"><b>Policy not attached to any entity.</b></Box>} />
      </CapabilityContainer>
      <CapabilityContainer id="iam.policy.entities-attached" title="Attached as a permissions boundary" counter={`(${boundaryRows.length})`}>
        <Table variant="embedded" items={boundaryRows} columnDefinitions={[{ id: "name", header: "Entity name", cell: (r) => r.name }, { id: "type", header: "Entity type", cell: (r) => r.type }]}
          empty={<Box textAlign="center" color="inherit"><b>Policy not set as a permissions boundary for any entity.</b></Box>} />
      </CapabilityContainer>
    </SpaceBetween>
  );
}

function VersionsTab({ policyArn, defaultVersionId, reloadPolicy }) {
  const notify = useNotify();
  const v = useAsync(() => api.listPolicyVersions(policyArn), [policyArn]);
  const [createModal, setCreateModal] = useState(false);
  const [doc, setDoc] = useState("");
  const [setDefault, setSetDefault] = useState(true);
  return (
    <CapabilityContainer id="iam.policy.versions" title="Versions of this policy" counter={`(${(v.data || []).length})`}
      actions={<Button onClick={() => setCreateModal(true)}>Create new version</Button>}>
      <Table variant="embedded" items={v.data || []} trackBy="VersionId"
        columnDefinitions={[
          { id: "v", header: "Policy version", cell: (x) => `${x.VersionId}${x.IsDefaultVersion === "true" ? " (Default)" : ""}` },
          { id: "c", header: "Creation time", cell: (x) => fmtDate(x.CreateDate) },
          { id: "actions", header: "Actions", cell: (x) => (
            <SpaceBetween direction="horizontal" size="xs">
              {x.IsDefaultVersion !== "true" && <Button onClick={async () => { await api.setDefaultPolicyVersion(policyArn, x.VersionId); notify.success(`Version ${x.VersionId} set as default.`); v.reload(); reloadPolicy(); }}>Set as default</Button>}
              {x.IsDefaultVersion !== "true" && <Button onClick={async () => { try { await api.deletePolicyVersion(policyArn, x.VersionId); notify.success(`Version ${x.VersionId} deleted.`); v.reload(); } catch (e) { notify.error(e); } }}>Delete</Button>}
            </SpaceBetween>
          ) },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No versions</b></Box>} />
      <Modal visible={createModal} onDismiss={() => setCreateModal(false)} size="large" header="Create policy version"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreateModal(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            try { JSON.parse(doc); } catch (e) { notify.error(new Error(`Not valid JSON: ${e.message}`)); return; }
            try { await api.createPolicyVersion(policyArn, doc, setDefault); notify.success("Policy version created."); setCreateModal(false); v.reload(); reloadPolicy(); }
            catch (e) { notify.error(e); }
          }}>Create version</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          <FormField label="Policy document"><Textarea rows={14} value={doc} onChange={({ detail }) => setDoc(detail.value)} spellcheck={false} /></FormField>
          <Toggle checked={setDefault} onChange={({ detail }) => setSetDefault(detail.checked)}>Set as default version</Toggle>
        </SpaceBetween>
      </Modal>
    </CapabilityContainer>
  );
}

export default function PolicyDetail({ params }) {
  const policyName = params.name;
  const notify = useNotify();
  const list = useAsync(() => api.listPolicies(), []);
  const [delModal, setDelModal] = useState(false);
  if (list.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (list.error) return <ErrorAlert error={list.error} />;
  const policy = (list.data || []).find((p) => p.PolicyName === policyName);
  if (!policy) return <ErrorAlert error={{ code: "NoSuchEntity", message: `Policy ${policyName} not found.` }} />;

  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={() => setDelModal(true)}>Delete</Button>}>{policy.PolicyName}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Policy details" columns={4} items={[
          ["Type", "Customer managed"], ["Creation time", fmtDate(policy.CreateDate)], ["Edited time", fmtDate(policy.UpdateDate)], ["ARN", policy.Arn],
        ]} />
        <Tabs tabs={[
          { id: "permissions", label: "Permissions", content: <PermissionsTab policy={policy} /> },
          { id: "entities", label: "Entities attached", content: <EntitiesTab policyArn={policy.Arn} /> },
          { id: "versions", label: "Policy versions", content: <VersionsTab policyArn={policy.Arn} defaultVersionId={policy.DefaultVersionId} reloadPolicy={list.reload} /> },
          { id: "last-accessed", label: "Last Accessed", content: <CapabilityContainer id="iam.last-accessed" title="Last accessed" /> },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={delModal} onDismiss={() => setDelModal(false)} resourceType="policy" names={[policyName]}
        onConfirm={async () => { await api.deletePolicy(policy.Arn); notify.success(`Policy "${policyName}" deleted.`); navigate("iam", "policies"); }} />
    </ContentLayout>
  );
}
