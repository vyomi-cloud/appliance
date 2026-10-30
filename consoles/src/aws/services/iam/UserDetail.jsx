/* IAM user detail — Summary + 5 tabs, all backed by real native calls except the
 * declared gaps (MFA, CloudTrail policy generator, non-CodeCommit/Keyspaces/X.509
 * credential sections, Last Accessed). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Checkbox from "@cloudscape-design/components/checkbox";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import SpaceBetween from "@cloudscape-design/components/space-between";
import TagEditor from "@cloudscape-design/components/tag-editor";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

function PermissionsTab({ userName, reload }) {
  const notify = useNotify();
  const p = useAsync(() => Promise.all([api.listAttachedUserPolicies(userName), api.listUserPolicies(userName), api.listPolicies()]), [userName]);
  const [boundaryModal, setBoundaryModal] = useState(false);
  const [boundaryArn, setBoundaryArn] = useState("");
  const [attachModal, setAttachModal] = useState(false);
  const [attachArn, setAttachArn] = useState("");
  const [inlineModal, setInlineModal] = useState(null); // {name, doc} | {name:"", doc:"{...}"} for create
  const user = useAsync(() => api.getUser(userName), [userName]);

  if (p.loading || user.loading) return <Spinner />;
  const [attached, inlineNames, allPolicies] = p.data;
  const rows = [
    ...attached.map((a) => ({ name: a.PolicyName, type: "Managed", via: "-", arn: a.PolicyArn })),
    ...inlineNames.map((n) => ({ name: n, type: "Inline", via: userName })),
  ];

  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="iam.user.permissions" title="Permissions policies" counter={`(${rows.length})`}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button onClick={() => setAttachModal(true)}>Add permissions</Button>
          <Button onClick={() => setInlineModal({ name: "", doc: '{\n  "Version": "2012-10-17",\n  "Statement": []\n}' })}>Create inline policy</Button>
        </SpaceBetween>}>
        <Table variant="embedded" items={rows} trackBy="name"
          columnDefinitions={[
            { id: "name", header: "Policy name", cell: (r) => r.name },
            { id: "type", header: "Type", cell: (r) => r.type },
            { id: "via", header: "Attached via", cell: (r) => r.via },
          ]}
          empty={<Box textAlign="center" color="inherit"><b>No permissions policies</b></Box>} />
      </CapabilityContainer>

      <CapabilityContainer id="iam.permissions-boundary" title="Permissions boundary"
        actions={<Button onClick={() => { setBoundaryArn(user.data?.PermissionsBoundary?.PermissionsBoundaryArn || ""); setBoundaryModal(true); }}>Set permissions boundary</Button>}>
        <ExpandableSection headerText="Permissions boundary" defaultExpanded>
          {user.data?.PermissionsBoundary ? <div>{user.data.PermissionsBoundary.PermissionsBoundaryArn}</div> : <Box color="text-body-secondary">No permissions boundary set.</Box>}
        </ExpandableSection>
      </CapabilityContainer>

      <CapabilityContainer id="iam.cloudtrail-policy-generator" title="Generate policy based on CloudTrail events" />

      <Modal visible={attachModal} onDismiss={() => setAttachModal(false)} header="Add permissions"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAttachModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={!attachArn} onClick={async () => {
            try { await api.attachUserPolicy(userName, attachArn); notify.success("Policy attached."); setAttachModal(false); setAttachArn(""); p.reload(); }
            catch (e) { notify.error(e); }
          }}>Attach policy</Button>
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
            try { await api.putUserPolicy(userName, inlineModal.name, inlineModal.doc); notify.success("Inline policy saved."); setInlineModal(null); p.reload(); }
            catch (e) { notify.error(e); }
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
          {user.data?.PermissionsBoundary && <Button onClick={async () => { await api.deleteUserPermissionsBoundary(userName); notify.success("Permissions boundary removed."); setBoundaryModal(false); user.reload(); }}>Remove boundary</Button>}
          <Button variant="primary" disabled={!boundaryArn} onClick={async () => {
            try { await api.putUserPermissionsBoundary(userName, boundaryArn); notify.success("Permissions boundary set."); setBoundaryModal(false); user.reload(); }
            catch (e) { notify.error(e); }
          }}>Set boundary</Button>
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

function GroupsTab({ userName }) {
  const notify = useNotify();
  const g = useAsync(() => Promise.all([api.listGroupsForUser(userName), api.listGroups()]), [userName]);
  const [sel, setSel] = useState([]);
  const [addModal, setAddModal] = useState(false);
  const [addSel, setAddSel] = useState([]);
  if (g.loading) return <Spinner />;
  const [memberGroups, allGroups] = g.data;
  const available = allGroups.filter((a) => !memberGroups.some((m) => m.GroupName === a.GroupName));
  return (
    <Container>
      <Table variant="embedded" items={memberGroups} trackBy="GroupName"
        selectionType="multi" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h2" counter={`(${memberGroups.length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={async () => { for (const x of sel) await api.removeUserFromGroup(x.GroupName, userName); notify.success("Removed from group(s)."); setSel([]); g.reload(); }}>Remove</Button>
            <Button variant="primary" onClick={() => setAddModal(true)}>Add user to groups</Button>
          </SpaceBetween>
        }>User groups membership</Header>}
        columnDefinitions={[
          { id: "name", header: "Group name", cell: (x) => x.GroupName },
          { id: "pol", header: "Attached policies", cell: (x) => (x.AttachedPolicies?.member ? "attached" : "-") },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>This user does not belong to any groups.</b></Box>} />
      <Modal visible={addModal} onDismiss={() => setAddModal(false)} header="Add user to groups"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAddModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={!addSel.length} onClick={async () => { for (const x of addSel) await api.addUserToGroup(x.GroupName, userName); notify.success("Added to group(s)."); setAddModal(false); setAddSel([]); g.reload(); }}>Add to groups</Button>
        </SpaceBetween></Box>}>
        <Table variant="embedded" items={available} trackBy="GroupName" selectionType="multi" selectedItems={addSel} onSelectionChange={({ detail }) => setAddSel(detail.selectedItems)}
          columnDefinitions={[{ id: "name", header: "Group name", cell: (x) => x.GroupName }]}
          empty={<Box textAlign="center" color="inherit"><b>No other groups available</b></Box>} />
      </Modal>
    </Container>
  );
}

function TagsTab({ userName }) {
  const notify = useNotify();
  const t = useAsync(() => api.listUserTags(userName), [userName]);
  const [edit, setEdit] = useState(null);
  return (
    <CapabilityContainer id="iam.user.tags" title="Tags" counter={`(${(t.data || []).length})`}
      actions={<Button onClick={() => setEdit((t.data || []).map((x) => ({ key: x.Key, value: x.Value })))}>Manage tags</Button>}>
      <Table variant="embedded" items={t.data || []} loading={t.loading}
        columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.Key }, { id: "v", header: "Value", cell: (x) => x.Value || "-" }]}
        empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>} />
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} size="large" header="Manage tags"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            try {
              const current = new Set((t.data || []).map((x) => x.Key));
              const next = edit.filter((x) => !x.markedForRemoval && x.key);
              const toRemove = [...current].filter((k) => !next.some((x) => x.key === k));
              if (toRemove.length) await api.untagUser(userName, toRemove);
              if (next.length) await api.tagUser(userName, next);
              notify.success("Tags updated."); setEdit(null); t.reload();
            } catch (e) { notify.error(e); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <TagEditor tags={edit} onChange={({ detail }) => setEdit(detail.tags)} />}
      </Modal>
    </CapabilityContainer>
  );
}

function AccessKeysSection({ userName }) {
  const notify = useNotify();
  const k = useAsync(() => api.listAccessKeys(userName), [userName]);
  const [created, setCreated] = useState(null);
  const create = async () => {
    try { const ak = await api.createAccessKey(userName); setCreated(ak); k.reload(); }
    catch (e) { notify.error(e); }
  };
  const download = () => {
    const csv = `Access key ID,Secret access key\n${created.AccessKeyId},${created.SecretAccessKey}\n`;
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${userName}_accessKeys.csv`; a.click();
  };
  return (
    <CapabilityContainer id="iam.user.access-keys" title="Access keys" actions={<Button disabled={(k.data || []).length >= 2} onClick={create}>Create access key</Button>}>
      <SpaceBetween size="m">
        {(k.data || []).length === 0 && <Box color="text-body-secondary">No access keys.</Box>}
        {(k.data || []).map((ak) => (
          <Container key={ak.AccessKeyId} header={<Header variant="h3" actions={
            <SpaceBetween direction="horizontal" size="xs">
              {ak.Status === "Active"
                ? <Button onClick={async () => { await api.updateAccessKey(userName, ak.AccessKeyId, "Inactive"); notify.success("Key deactivated."); k.reload(); }}>Deactivate</Button>
                : <Button onClick={async () => { await api.updateAccessKey(userName, ak.AccessKeyId, "Active"); notify.success("Key activated."); k.reload(); }}>Activate</Button>}
              <Button onClick={async () => { await api.deleteAccessKey(userName, ak.AccessKeyId); notify.success("Key deleted."); k.reload(); }}>Delete</Button>
            </SpaceBetween>
          }>{ak.AccessKeyId}</Header>}>
            <KeyValue columns={3} items={[
              ["Description", "-"], ["Status", <StatusIndicator key="s" type={ak.Status === "Active" ? "success" : "stopped"}>{ak.Status}</StatusIndicator>],
              ["Last used", "-"], ["Created", fmtDate(ak.CreateDate)], ["Last used region", "-"], ["Last used service", "-"],
            ]} />
          </Container>
        ))}
      </SpaceBetween>
      <Modal visible={!!created} onDismiss={() => setCreated(null)} header="Access key created"
        footer={<Box float="right"><Button variant="primary" onClick={() => setCreated(null)}>Done</Button></Box>}>
        {created && <SpaceBetween size="m">
          <FormField label="Access key"><Input value={created.AccessKeyId} readOnly ariaLabel="Access key" /></FormField>
          <FormField label="Secret access key"><Input value={created.SecretAccessKey} readOnly ariaLabel="Secret access key" /></FormField>
          <Button onClick={download}>Download .csv file</Button>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

function ConsoleSignInSection({ userName, reload }) {
  const notify = useNotify();
  const lp = useAsync(() => api.getLoginProfile(userName), [userName]);
  const [enable, setEnable] = useState(false);
  const [pwType, setPwType] = useState("auto");
  const [customPw, setCustomPw] = useState("");
  const [resetRequired, setResetRequired] = useState(true);
  const [result, setResult] = useState(null);
  const submit = async () => {
    const pw = pwType === "auto" ? Math.random().toString(36).slice(2, 10) + "Aa1!" : customPw;
    try { await api.createLoginProfile(userName, pw, resetRequired); setResult(pw); lp.reload(); }
    catch (e) { notify.error(e); }
  };
  return (
    <CapabilityContainer id="iam.user.console-password" title="Console sign-in"
      actions={!lp.data && <Button onClick={() => setEnable(true)}>Enable console access</Button>}>
      <KeyValue columns={2} items={[
        ["Console sign-in link", `https://123456789012.signin.aws.amazon.com/console`],
        ["Console password", lp.loading ? "-" : (lp.data ? "Enabled" : "Disabled")],
      ]} />
      <Modal visible={enable} onDismiss={() => setEnable(false)} header="Enable console access"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEnable(false)}>Cancel</Button>
          <Button variant="primary" disabled={pwType === "custom" && !customPw} onClick={async () => { await submit(); setEnable(false); }}>Apply</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          <RadioGroup value={pwType} onChange={({ detail }) => setPwType(detail.value)}
            items={[{ value: "auto", label: "Autogenerated password" }, { value: "custom", label: "Custom password" }]} />
          {pwType === "custom" && <FormField label="Console password"><Input type="password" value={customPw} onChange={({ detail }) => setCustomPw(detail.value)} ariaLabel="Console password" /></FormField>}
          <Checkbox checked={resetRequired} onChange={({ detail }) => setResetRequired(detail.checked)}>Users must create a new password at next sign-in</Checkbox>
        </SpaceBetween>
      </Modal>
      <Modal visible={!!result} onDismiss={() => setResult(null)} header="Console access enabled"
        footer={<Box float="right"><Button variant="primary" onClick={() => setResult(null)}>Close</Button></Box>}>
        <FormField label="Console password" description="Shown once."><Input value={result || ""} readOnly ariaLabel="Console password" /></FormField>
      </Modal>
    </CapabilityContainer>
  );
}

function SecurityCredentialsTab({ userName }) {
  return (
    <SpaceBetween size="l">
      <ConsoleSignInSection userName={userName} />
      <CapabilityContainer id="iam.user.mfa" title="Multi-factor authentication (MFA)" />
      <AccessKeysSection userName={userName} />
      <CapabilityContainer id="iam.security-credentials.codecommit" title="API keys" />
      <CapabilityContainer id="iam.security-credentials.codecommit" title="SSH public keys for AWS CodeCommit" />
      <CapabilityContainer id="iam.security-credentials.codecommit" title="HTTPS Git credentials for AWS CodeCommit" />
      <CapabilityContainer id="iam.security-credentials.codecommit" title="Credentials for Amazon Keyspaces (for Apache Cassandra)" />
      <CapabilityContainer id="iam.security-credentials.codecommit" title="X.509 Signing certificates" />
    </SpaceBetween>
  );
}

export default function UserDetail({ params }) {
  const userName = params.name;
  const notify = useNotify();
  const u = useAsync(() => api.getUser(userName), [userName]);
  const keys = useAsync(() => api.listAccessKeys(userName), [userName]);
  const [delModal, setDelModal] = useState(false);
  if (u.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (u.error) return <ErrorAlert error={u.error} />;
  const user = u.data;
  const ks = keys.data || [];

  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={() => setDelModal(true)}>Delete</Button>}>{user.UserName}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Summary" columns={3} items={[
          ["ARN", user.Arn], ["Console access", "-"], ["Access key 1", ks[0]?.AccessKeyId || "-"],
          ["Created", fmtDate(user.CreateDate)], ["Last console sign-in", "-"], ["Access key 2", ks[1]?.AccessKeyId || "-"],
        ]} />
        <Tabs tabs={[
          { id: "permissions", label: "Permissions", content: <PermissionsTab userName={userName} reload={u.reload} /> },
          { id: "groups", label: "Groups", content: <GroupsTab userName={userName} /> },
          { id: "tags", label: "Tags", content: <TagsTab userName={userName} /> },
          { id: "security", label: "Security credentials", content: <SecurityCredentialsTab userName={userName} /> },
          { id: "last-accessed", label: "Last Accessed", content: <CapabilityContainer id="iam.last-accessed" title="Last accessed" /> },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={delModal} onDismiss={() => setDelModal(false)} resourceType="user" names={[userName]}
        onConfirm={async () => { await api.deleteUser(userName); notify.success(`User "${userName}" deleted.`); navigate("iam", "users"); }} />
    </ContentLayout>
  );
}
