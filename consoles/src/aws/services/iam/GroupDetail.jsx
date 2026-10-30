/* IAM group detail — Summary + Users / Permissions / Access Advisor tabs. */
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
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

function UsersTab({ groupName }) {
  const notify = useNotify();
  const g = useAsync(() => Promise.all([api.getGroup(groupName), api.listUsers()]), [groupName]);
  const [sel, setSel] = useState([]);
  const [addModal, setAddModal] = useState(false);
  const [addSel, setAddSel] = useState([]);
  if (g.loading) return <Spinner />;
  const [{ users: members }, allUsers] = g.data;
  const available = allUsers.filter((u) => !members.some((m) => m.UserName === u.UserName));
  return (
    <Container>
      <Table variant="embedded" items={members} trackBy="UserName"
        selectionType="multi" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h2" counter={`(${members.length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={async () => { for (const x of sel) await api.removeUserFromGroup(groupName, x.UserName); notify.success("Removed user(s)."); setSel([]); g.reload(); }}>Remove</Button>
            <Button variant="primary" onClick={() => setAddModal(true)}>Add users</Button>
          </SpaceBetween>
        }>Users in this group</Header>}
        filter={undefined}
        columnDefinitions={[
          { id: "name", header: "User name", cell: (x) => x.UserName },
          { id: "groups", header: "Groups", cell: () => "-" },
          { id: "last", header: "Last activity", cell: () => "-" },
          { id: "created", header: "Creation time", cell: (x) => fmtDate(x.CreateDate) },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No users</b></Box>} />
      <Modal visible={addModal} onDismiss={() => setAddModal(false)} header="Add users"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAddModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={!addSel.length} onClick={async () => { for (const x of addSel) await api.addUserToGroup(groupName, x.UserName); notify.success("User(s) added."); setAddModal(false); setAddSel([]); g.reload(); }}>Add users</Button>
        </SpaceBetween></Box>}>
        <Table variant="embedded" items={available} trackBy="UserName" selectionType="multi" selectedItems={addSel} onSelectionChange={({ detail }) => setAddSel(detail.selectedItems)}
          columnDefinitions={[{ id: "name", header: "User name", cell: (x) => x.UserName }]}
          empty={<Box textAlign="center" color="inherit"><b>No other users available</b></Box>} />
      </Modal>
    </Container>
  );
}

function GroupPermissionsTab({ groupName }) {
  const notify = useNotify();
  const p = useAsync(() => Promise.all([api.listAttachedGroupPolicies(groupName), api.listGroupPolicies(groupName), api.listPolicies()]), [groupName]);
  const [attachModal, setAttachModal] = useState(false);
  const [attachArn, setAttachArn] = useState("");
  const [inlineModal, setInlineModal] = useState(null);
  if (p.loading) return <Spinner />;
  const [attached, inlineNames, allPolicies] = p.data;
  const rows = [...attached.map((a) => ({ name: a.PolicyName, type: "Managed", desc: "-", arn: a.PolicyArn })), ...inlineNames.map((n) => ({ name: n, type: "Inline", desc: "-" }))];
  return (
    <CapabilityContainer id="iam.role.permissions" title="Permissions policies" counter={`(${rows.length})`}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button onClick={() => setAttachModal(true)}>Attach policies</Button>
        <Button onClick={() => setInlineModal({ name: "", doc: '{\n  "Version": "2012-10-17",\n  "Statement": []\n}' })}>Create inline policy</Button>
      </SpaceBetween>}>
      <Table variant="embedded" items={rows} trackBy="name"
        columnDefinitions={[{ id: "name", header: "Policy name", cell: (r) => r.name }, { id: "type", header: "Type", cell: (r) => r.type }, { id: "desc", header: "Description", cell: (r) => r.desc }]}
        empty={<Box textAlign="center" color="inherit"><b>No permissions policies</b></Box>} />
      <Modal visible={attachModal} onDismiss={() => setAttachModal(false)} header="Attach policies"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAttachModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={!attachArn} onClick={async () => { await api.attachGroupPolicy(groupName, attachArn); notify.success("Policy attached."); setAttachModal(false); setAttachArn(""); p.reload(); }}>Attach policy</Button>
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
            await api.putGroupPolicy(groupName, inlineModal.name, inlineModal.doc); notify.success("Inline policy saved."); setInlineModal(null); p.reload();
          }}>Create policy</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          <FormField label="Policy name"><Input value={inlineModal?.name || ""} onChange={({ detail }) => setInlineModal((m) => ({ ...m, name: detail.value }))} ariaLabel="Policy name" /></FormField>
          <FormField label="Policy document"><Textarea rows={14} value={inlineModal?.doc || ""} onChange={({ detail }) => setInlineModal((m) => ({ ...m, doc: detail.value }))} spellcheck={false} /></FormField>
        </SpaceBetween>
      </Modal>
    </CapabilityContainer>
  );
}

export default function GroupDetail({ params }) {
  const groupName = params.name;
  const notify = useNotify();
  const g = useAsync(() => api.getGroup(groupName), [groupName]);
  const [delModal, setDelModal] = useState(false);
  if (g.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (g.error) return <ErrorAlert error={g.error} />;
  const group = g.data.group;

  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={() => setDelModal(true)}>Delete</Button>}>{group.GroupName}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Summary" columns={3} items={[["User group name", group.GroupName], ["Creation time", fmtDate(group.CreateDate)], ["ARN", group.Arn]]} />
        <Tabs tabs={[
          { id: "users", label: "Users", content: <UsersTab groupName={groupName} /> },
          { id: "permissions", label: "Permissions", content: <GroupPermissionsTab groupName={groupName} /> },
          { id: "access-advisor", label: "Access Advisor", content: <CapabilityContainer id="iam.last-accessed" title="Last accessed" /> },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={delModal} onDismiss={() => setDelModal(false)} resourceType="group" names={[groupName]}
        onConfirm={async () => { await api.deleteGroup(groupName); notify.success(`Group "${groupName}" deleted.`); navigate("iam", "groups"); }} />
    </ContentLayout>
  );
}
