/* Role detail — Summary + Permissions / Trust relationships / Tags / Last Accessed tabs.
 * Trust relationships is a real JSON editor (UpdateAssumeRolePolicy) despite the native
 * console presenting it read-only in some views — Vyomi can store+return it faithfully. */
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
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Select from "@cloudscape-design/components/select";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

function RolePermissionsTab({ roleName }) {
  const notify = useNotify();
  const p = useAsync(() => Promise.all([api.listAttachedRolePolicies(roleName), api.listRolePolicies(roleName), api.listPolicies()]), [roleName]);
  const role = useAsync(() => api.getRole(roleName), [roleName]);
  const [attachModal, setAttachModal] = useState(false);
  const [attachArn, setAttachArn] = useState("");
  const [inlineModal, setInlineModal] = useState(null);
  const [boundaryModal, setBoundaryModal] = useState(false);
  const [boundaryArn, setBoundaryArn] = useState("");
  if (p.loading || role.loading) return <Spinner />;
  const [attached, inlineNames, allPolicies] = p.data;
  const rows = [...attached.map((a) => ({ name: a.PolicyName, type: "Managed", entities: "-" })), ...inlineNames.map((n) => ({ name: n, type: "Inline", entities: "-" }))];
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="iam.role.permissions" title="Permissions policies" counter={`(${rows.length})`}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button onClick={() => setAttachModal(true)}>Add permissions</Button>
          <Button onClick={() => setInlineModal({ name: "", doc: '{\n  "Version": "2012-10-17",\n  "Statement": []\n}' })}>Create inline policy</Button>
        </SpaceBetween>}>
        <Table variant="embedded" items={rows} trackBy="name"
          columnDefinitions={[{ id: "name", header: "Policy name", cell: (r) => r.name }, { id: "type", header: "Type", cell: (r) => r.type }, { id: "entities", header: "Attached entities", cell: (r) => r.entities }]}
          empty={<Box textAlign="center" color="inherit"><b>No permissions policies</b></Box>} />
      </CapabilityContainer>
      <Container header={<Header variant="h2" actions={<SpaceBetween direction="horizontal" size="xs">
        <Button onClick={() => setAttachModal(true)}>Simulate</Button>
        <Button onClick={() => setAttachModal(true)}>Remove</Button>
        <Button onClick={() => setAttachModal(true)}>Add permissions</Button>
      </SpaceBetween>}>Permissions policies (customer role actions)</Header>}>
        <FormField label="Add permissions">
          <Select selectedOption={null} onChange={({ detail }) => { if (detail.selectedOption.value === "attach") setAttachModal(true); else setInlineModal({ name: "", doc: '{\n  "Version": "2012-10-17",\n  "Statement": []\n}' }); }}
            options={[{ value: "attach", label: "Attach policies" }, { value: "inline", label: "Create inline policy" }]} placeholder="Add permissions" />
        </FormField>
      </Container>
      <CapabilityContainer id="iam.permissions-boundary" title="Permissions boundary"
        actions={<Button onClick={() => { setBoundaryArn(role.data?.PermissionsBoundary?.PermissionsBoundaryArn || ""); setBoundaryModal(true); }}>Set permissions boundary</Button>}>
        <ExpandableSection headerText="Permissions boundary" defaultExpanded>
          {role.data?.PermissionsBoundary ? <div>{role.data.PermissionsBoundary.PermissionsBoundaryArn}</div> : <Box color="text-body-secondary">No permissions boundary set.</Box>}
        </ExpandableSection>
      </CapabilityContainer>
      <Modal visible={attachModal} onDismiss={() => setAttachModal(false)} header="Add permissions"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAttachModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={!attachArn} onClick={async () => { await api.attachRolePolicy(roleName, attachArn); notify.success("Policy attached."); setAttachModal(false); setAttachArn(""); p.reload(); }}>Attach policy</Button>
        </SpaceBetween></Box>}>
        <FormField label="Policy">
          <Select selectedOption={attachArn ? { value: attachArn, label: allPolicies.find((x) => x.Arn === attachArn)?.PolicyName } : null}
            onChange={({ detail }) => setAttachArn(detail.selectedOption.value)}
            options={allPolicies.map((pl) => ({ value: pl.Arn, label: pl.PolicyName }))} placeholder="Choose a policy" />
        </FormField>
      </Modal>
      <Modal visible={!!inlineModal} onDismiss={() => setInlineModal(null)} size="large" header="Create inline policy"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setInlineModal(null)}>Cancel</Button>
          <Button variant="primary" disabled={!inlineModal?.name} onClick={async () => {
            try { JSON.parse(inlineModal.doc); } catch (e) { notify.error(new Error(`Not valid JSON: ${e.message}`)); return; }
            await api.putRolePolicy(roleName, inlineModal.name, inlineModal.doc); notify.success("Inline policy saved."); setInlineModal(null); p.reload();
          }}>Create policy</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          <FormField label="Policy name"><Input value={inlineModal?.name || ""} onChange={({ detail }) => setInlineModal((m) => ({ ...m, name: detail.value }))} ariaLabel="Policy name" /></FormField>
          <FormField label="Policy document"><Textarea rows={14} value={inlineModal?.doc || ""} onChange={({ detail }) => setInlineModal((m) => ({ ...m, doc: detail.value }))} spellcheck={false} /></FormField>
        </SpaceBetween>
      </Modal>
      <Modal visible={boundaryModal} onDismiss={() => setBoundaryModal(false)} header="Set permissions boundary"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setBoundaryModal(false)}>Cancel</Button>
          {role.data?.PermissionsBoundary && <Button onClick={async () => { await api.deleteRolePermissionsBoundary(roleName); notify.success("Permissions boundary removed."); setBoundaryModal(false); role.reload(); }}>Remove boundary</Button>}
          <Button variant="primary" disabled={!boundaryArn} onClick={async () => { await api.putRolePermissionsBoundary(roleName, boundaryArn); notify.success("Permissions boundary set."); setBoundaryModal(false); role.reload(); }}>Set boundary</Button>
        </SpaceBetween></Box>}>
        <FormField label="Policy">
          <Select selectedOption={boundaryArn ? { value: boundaryArn, label: allPolicies.find((x) => x.Arn === boundaryArn)?.PolicyName } : null}
            onChange={({ detail }) => setBoundaryArn(detail.selectedOption.value)}
            options={allPolicies.map((pl) => ({ value: pl.Arn, label: pl.PolicyName }))} placeholder="Choose a policy" />
        </FormField>
      </Modal>
    </SpaceBetween>
  );
}

function TrustTab({ roleName, role, reload }) {
  const notify = useNotify();
  const [edit, setEdit] = useState(false);
  const [doc, setDoc] = useState("");
  const current = JSON.stringify(role.AssumeRolePolicyDocument || {}, null, 2);
  return (
    <CapabilityContainer id="iam.role.trust-policy" title="Trusted entities" actions={<Button onClick={() => { setDoc(current); setEdit(true); }}>Edit trust policy</Button>}>
      <FormField label="Trust policy" description="JSON trust policy document">
        <Textarea rows={16} value={current} readOnly spellcheck={false} />
      </FormField>
      <Modal visible={edit} onDismiss={() => setEdit(false)} size="large" header="Edit trust policy"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            try { JSON.parse(doc); } catch (e) { notify.error(new Error(`Not valid JSON: ${e.message}`)); return; }
            try { await api.updateAssumeRolePolicy(roleName, doc); notify.success("Trust policy updated."); setEdit(false); reload(); }
            catch (e) { notify.error(e); }
          }}>Update policy</Button>
        </SpaceBetween></Box>}>
        <Textarea rows={18} value={doc} onChange={({ detail }) => setDoc(detail.value)} spellcheck={false} />
      </Modal>
    </CapabilityContainer>
  );
}

function RoleTagsTab({ roleName }) {
  const notify = useNotify();
  const t = useAsync(() => api.listRoleTags(roleName), [roleName]);
  const [edit, setEdit] = useState(null);
  return (
    <CapabilityContainer id="iam.role.tags" title="Tags" counter={`(${(t.data || []).length})`}
      actions={<Button onClick={() => setEdit((t.data || []).map((x) => ({ key: x.Key, value: x.Value })))}>Add new tag</Button>}>
      <Table variant="embedded" items={t.data || []} loading={t.loading}
        columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.Key }, { id: "v", header: "Value", cell: (x) => x.Value || "-" }]}
        empty={<Box textAlign="center" color="inherit"><b>No tags associated with the resource</b></Box>} />
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} size="large" header="Manage tags"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            const current = new Set((t.data || []).map((x) => x.Key));
            const next = edit.filter((x) => !x.markedForRemoval && x.key);
            const toRemove = [...current].filter((k) => !next.some((x) => x.key === k));
            if (toRemove.length) await api.untagRole(roleName, toRemove);
            if (next.length) await api.tagRole(roleName, next);
            notify.success("Tags updated."); setEdit(null); t.reload();
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <TagEditor tags={edit} onChange={({ detail }) => setEdit(detail.tags)} />}
      </Modal>
    </CapabilityContainer>
  );
}

export default function RoleDetail({ params }) {
  const roleName = params.name;
  const notify = useNotify();
  const r = useAsync(() => api.getRole(roleName), [roleName]);
  const [delModal, setDelModal] = useState(false);
  if (r.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (r.error) return <ErrorAlert error={r.error} />;
  const role = r.data;

  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={() => setDelModal(true)}>Delete</Button>}>{role.RoleName}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Summary" columns={4} items={[
          ["Creation date", fmtDate(role.CreateDate)], ["ARN", role.Arn], ["Last activity", "-"], ["Maximum session duration", `${role.MaxSessionDuration || 3600} seconds`],
        ]} />
        <Tabs tabs={[
          { id: "permissions", label: "Permissions", content: <RolePermissionsTab roleName={roleName} /> },
          { id: "trust", label: "Trust relationships", content: <TrustTab roleName={roleName} role={role} reload={r.reload} /> },
          { id: "tags", label: "Tags", content: <RoleTagsTab roleName={roleName} /> },
          { id: "last-accessed", label: "Last Accessed", content: <CapabilityContainer id="iam.last-accessed" title="Last accessed" /> },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={delModal} onDismiss={() => setDelModal(false)} resourceType="role" names={[roleName]}
        onConfirm={async () => { await api.deleteRole(roleName); notify.success(`Role "${roleName}" deleted.`); navigate("iam", "roles"); }} />
    </ContentLayout>
  );
}
