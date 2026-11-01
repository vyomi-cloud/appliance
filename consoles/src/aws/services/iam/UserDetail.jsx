/* IAM user detail — Summary + 5 tabs, all backed by real native calls except the
 * declared gap (non-CodeCommit/Keyspaces/X.509 credential sections — see
 * iam.security-credentials.codecommit). MFA devices are real (assignment + resync),
 * limited only by there being no console sign-in flow to challenge the code against.
 * Last Accessed and the CloudTrail policy generator are real too, mined from Vyomi's
 * own native-wire activity log rather than CloudTrail (see LastAccessed.jsx). */
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
import { LastAccessedTab, CloudTrailPolicyGenerator } from "./LastAccessed.jsx";
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

      <CloudTrailPolicyGenerator arn={user.data?.Arn} />

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

function MfaSection({ userName }) {
  const notify = useNotify();
  const m = useAsync(() => api.listMfaDevices(userName), [userName]);
  const [sel, setSel] = useState([]);
  const [assign, setAssign] = useState(null); // {step, name, device} | null
  const [codes, setCodes] = useState({ a: "", b: "" });
  const [resync, setResync] = useState(null); // {device, a, b} | null
  const devices = m.data || [];

  const createDevice = async () => {
    try { const device = await api.createVirtualMfaDevice(assign.name); setAssign((a) => ({ ...a, step: 2, device })); }
    catch (e) { notify.error(e); }
  };
  const enable = async () => {
    try {
      await api.enableMfaDevice(userName, assign.device.SerialNumber, codes.a, codes.b);
      notify.success("MFA device assigned."); setAssign(null); setCodes({ a: "", b: "" }); m.reload();
    } catch (e) { notify.error(e); }
  };
  const remove = async () => {
    try {
      for (const d of sel) { await api.deactivateMfaDevice(userName, d.SerialNumber); await api.deleteVirtualMfaDevice(d.SerialNumber); }
      notify.success("MFA device removed."); setSel([]); m.reload();
    } catch (e) { notify.error(e); }
  };
  const doResync = async () => {
    try { await api.resyncMfaDevice(userName, resync.device.SerialNumber, resync.a, resync.b); notify.success("MFA device resynchronized."); setResync(null); }
    catch (e) { notify.error(e); }
  };

  return (
    <CapabilityContainer id="iam.user.mfa" title="Multi-factor authentication (MFA)" counter={`(${devices.length})`}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={sel.length !== 1} onClick={() => setResync({ device: sel[0], a: "", b: "" })}>Resync</Button>
        <Button disabled={!sel.length} onClick={remove}>Remove</Button>
        <Button variant="primary" onClick={() => setAssign({ step: 1, name: "", device: null })}>Assign MFA device</Button>
      </SpaceBetween>}>
      <Table variant="embedded" items={devices} trackBy="SerialNumber"
        selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        columnDefinitions={[
          { id: "type", header: "Type", cell: () => "Virtual" },
          { id: "id", header: "Identifier", cell: (d) => d.SerialNumber },
          { id: "cert", header: "Certifications", cell: () => "-" },
          { id: "created", header: "Created on", cell: (d) => fmtDate(d.EnableDate) },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No MFA devices.</b> Assign an MFA device to improve the security of your AWS environment.</Box>} />

      <Modal visible={!!assign} onDismiss={() => setAssign(null)} header="Assign MFA device"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAssign(null)}>Cancel</Button>
          {assign?.step === 1
            ? <Button variant="primary" disabled={!assign.name} onClick={createDevice}>Next</Button>
            : <Button variant="primary" disabled={!codes.a || !codes.b} onClick={enable}>Assign MFA</Button>}
        </SpaceBetween></Box>}>
        {assign?.step === 1 && <FormField label="Device name"><Input value={assign.name} onChange={({ detail }) => setAssign((a) => ({ ...a, name: detail.value }))} ariaLabel="Device name" /></FormField>}
        {assign?.step === 2 && <SpaceBetween size="m">
          <FormField label="Secret key" description="Enter this key into your virtual MFA application (there is no camera to scan a QR code in this environment).">
            <Input value={assign.device.Base32StringSeed} readOnly ariaLabel="Secret key" />
          </FormField>
          <FormField label="MFA code 1"><Input value={codes.a} onChange={({ detail }) => setCodes((c) => ({ ...c, a: detail.value }))} ariaLabel="MFA code 1" /></FormField>
          <FormField label="MFA code 2"><Input value={codes.b} onChange={({ detail }) => setCodes((c) => ({ ...c, b: detail.value }))} ariaLabel="MFA code 2" /></FormField>
        </SpaceBetween>}
      </Modal>

      <Modal visible={!!resync} onDismiss={() => setResync(null)} header="Resynchronize MFA device"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setResync(null)}>Cancel</Button>
          <Button variant="primary" disabled={!resync?.a || !resync?.b} onClick={doResync}>Resynchronize</Button>
        </SpaceBetween></Box>}>
        {resync && <SpaceBetween size="m">
          <FormField label="MFA code 1"><Input value={resync.a} onChange={({ detail }) => setResync((r) => ({ ...r, a: detail.value }))} ariaLabel="MFA code 1" /></FormField>
          <FormField label="MFA code 2"><Input value={resync.b} onChange={({ detail }) => setResync((r) => ({ ...r, b: detail.value }))} ariaLabel="MFA code 2" /></FormField>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

function SecurityCredentialsTab({ userName }) {
  return (
    <SpaceBetween size="l">
      <ConsoleSignInSection userName={userName} />
      <MfaSection userName={userName} />
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
          { id: "last-accessed", label: "Last Accessed", content: <LastAccessedTab arn={user.Arn} /> },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={delModal} onDismiss={() => setDelModal(false)} resourceType="user" names={[userName]}
        onConfirm={async () => { await api.deleteUser(userName); notify.success(`User "${userName}" deleted.`); navigate("iam", "users"); }} />
    </ContentLayout>
  );
}
