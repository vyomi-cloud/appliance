/* Multi-account IAM pages on the real AWS Organizations backend (core/organizations_core.py):
 * Organization activity, Account access manager (OU/account lifecycle), Root access management,
 * Assign delegated administrator, and the centralized-root-access panel of Account settings. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Toggle from "@cloudscape-design/components/toggle";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { EventLog } from "./CredentialSections.jsx";
import { OrgGate, OrgStructure, parentLabel, useOrgModel } from "./OrgKit.jsx";
import * as api from "./api.js";

const IAM_SP = "iam.amazonaws.com";

export function OrganizationActivity() {
  const model = useOrgModel();
  const ev = useAsync(() => api.listIamEvents(500), []);
  // The IAM event log records this (management) account's own admin actions; member accounts have no activity.
  const last = (a) => (a.Id === model.data?.org?.MasterAccountId && (ev.data || []).length ? fmtDate(ev.data[0].EventTime) : "No activity recorded");
  return (
    <SpaceBetween size="l">
      <OrgGate model={model} title="Organization activity">{(m) => (
        <CapabilityContainer id="iam.organizations" title="Organization activity">
          <OrgStructure m={m} title="Organization structure" extra={(a) => `last IAM activity: ${last(a)}`}
            extraCols={[{ id: "activity", header: "Last IAM activity", cell: (a) => last(a) }]} />
        </CapabilityContainer>
      )}</OrgGate>
      <Box padding={{ horizontal: "l", bottom: "l" }}><EventLog /></Box>
    </SpaceBetween>
  );
}

function Dialog({ header, visible, onDismiss, onSubmit, submitLabel, disabled, children }) {
  const [busy, setBusy] = useState(false);
  const notify = useNotify();
  return (
    <Modal visible={visible} onDismiss={onDismiss} header={header}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={disabled} onClick={async () => {
          setBusy(true);
          try { await onSubmit(); onDismiss(); } catch (e) { notify.error(e); } finally { setBusy(false); }
        }}>{submitLabel}</Button>
      </SpaceBetween></Box>}>{children}</Modal>
  );
}

const opt = (value, label) => ({ value, label });

export function AccountAccessManager() {
  const notify = useNotify();
  const model = useOrgModel();
  const hs = useAsync(() => api.listHandshakes(), []);
  const [dlg, setDlg] = useState(null);
  const [f, setF] = useState({});
  const [sel, setSel] = useState([]);
  const set = (k) => ({ detail }) => setF((x) => ({ ...x, [k]: detail.value ?? detail.selectedOption }));
  const open = (name, init = {}) => { setF(init); setDlg(name); };
  const close = () => setDlg(null);
  const done = (msg) => { notify.success(msg); model.reload(); hs.reload(); setSel([]); };
  return (
    <OrgGate model={model} title="Account access manager">{(m) => {
      const parents = [opt(m.root.Id, "Root"), ...m.ous.map((u) => opt(u.Id, parentLabel(m, u.Id)))];
      const acct = sel[0];
      return (
        <SpaceBetween size="l">
          <CapabilityContainer id="iam.organizations" title="Account access manager">
            <OrgStructure m={m} title="Organization accounts"
              selection={{ selectionType: "single", selectedItems: sel, onSelectionChange: ({ detail }) => setSel(detail.selectedItems) }}
              actions={<SpaceBetween direction="horizontal" size="xs">
                <Button onClick={() => open("ou", { parent: parents[0] })}>Create OU</Button>
                <Button onClick={() => open("account")}>Create account</Button>
                <Button onClick={() => open("invite")}>Invite account</Button>
                <Button disabled={!acct} onClick={() => open("move", { dest: parents[0] })}>Move</Button>
                <Button disabled={!acct || acct.Id === m.org.MasterAccountId} onClick={async () => { try { await api.removeAccount(acct.Id); done(`Account ${acct.Id} removed from the organization.`); } catch (e) { notify.error(e); } }}>Remove</Button>
                <Button disabled={!acct || acct.Id === m.org.MasterAccountId || acct.Status === "SUSPENDED"} onClick={async () => { try { await api.closeAccount(acct.Id); done(`Account ${acct.Id} closed.`); } catch (e) { notify.error(e); } }}>Close account</Button>
              </SpaceBetween>} />
          </CapabilityContainer>
          <Table variant="container" items={m.ous} trackBy="Id"
            header={<Header variant="h2" counter={`(${m.ous.length})`}>Organizational units</Header>}
            columnDefinitions={[
              { id: "name", header: "OU name", isRowHeader: true, cell: (u) => parentLabel(m, u.Id) },
              { id: "id", header: "OU ID", cell: (u) => u.Id },
              { id: "act", header: "Actions", cell: (u) => <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-link" onClick={() => open("rename", { ou: u, name: u.Name })}>Rename</Button>
                <Button variant="inline-link" onClick={async () => { try { await api.deleteOU(u.Id); done(`OU ${u.Name} deleted.`); } catch (e) { notify.error(e); } }}>Delete</Button>
              </SpaceBetween> },
            ]}
            empty={<Box textAlign="center"><b>No organizational units</b></Box>} />
          <Table variant="container" items={hs.data || []} loading={hs.loading} trackBy="Id"
            header={<Header variant="h2" counter={`(${(hs.data || []).length})`}>Invitations (handshakes)</Header>}
            columnDefinitions={[
              { id: "id", header: "Handshake ID", isRowHeader: true, cell: (h) => h.Id },
              { id: "action", header: "Action", cell: (h) => h.Action },
              { id: "target", header: "Invited", cell: (h) => h.Parties?.[1]?.Id || "-" },
              { id: "state", header: "State", cell: (h) => h.State },
              { id: "act", header: "Actions", cell: (h) => h.State === "OPEN" && h.Action === "INVITE" && <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-link" onClick={async () => { try { await api.acceptHandshake(h.Id); done("Invitation accepted - the account joined the organization."); } catch (e) { notify.error(e); } }}>Accept as invitee</Button>
                <Button variant="inline-link" onClick={async () => { try { await api.cancelHandshake(h.Id); done("Invitation canceled."); } catch (e) { notify.error(e); } }}>Cancel</Button>
              </SpaceBetween> },
            ]}
            empty={<Box textAlign="center"><b>No invitations</b></Box>} />

          <Dialog header="Create organizational unit" visible={dlg === "ou"} onDismiss={close} submitLabel="Create organizational unit" disabled={!f.name}
            onSubmit={async () => { await api.createOU(f.parent.value, f.name); done(`OU ${f.name} created.`); }}>
            <SpaceBetween size="m">
              <FormField label="Organizational unit name"><Input ariaLabel="Organizational unit name" value={f.name || ""} onChange={set("name")} /></FormField>
              <FormField label="Parent"><Select selectedOption={f.parent || null} options={parents} onChange={set("parent")} /></FormField>
            </SpaceBetween>
          </Dialog>
          <Dialog header="Rename organizational unit" visible={dlg === "rename"} onDismiss={close} submitLabel="Save" disabled={!f.name}
            onSubmit={async () => { await api.renameOU(f.ou.Id, f.name); done("OU renamed."); }}>
            <FormField label="Organizational unit name"><Input ariaLabel="OU name" value={f.name || ""} onChange={set("name")} /></FormField>
          </Dialog>
          <Dialog header="Create AWS account" visible={dlg === "account"} onDismiss={close} submitLabel="Create AWS account" disabled={!f.name || !f.email}
            onSubmit={async () => {
              const st = await api.createAccount(f.email, f.name);
              if (st.State === "FAILED") throw { code: "CreateAccountFailed", message: "An account with that email already exists." };
              done(`Account ${f.name} created (${st.AccountId}).`);
            }}>
            <SpaceBetween size="m">
              <FormField label="AWS account name"><Input ariaLabel="AWS account name" value={f.name || ""} onChange={set("name")} /></FormField>
              <FormField label="Email address of the account's owner"><Input ariaLabel="Email address" value={f.email || ""} onChange={set("email")} /></FormField>
            </SpaceBetween>
          </Dialog>
          <Dialog header="Invite existing AWS account" visible={dlg === "invite"} onDismiss={close} submitLabel="Send invitation" disabled={!/^\d{12}$/.test(f.id || "")}
            onSubmit={async () => { await api.inviteAccount(f.id, "ACCOUNT"); done(`Invitation sent to ${f.id}.`); }}>
            <FormField label="AWS account ID" constraintText="12 digits"><Input ariaLabel="AWS account ID" value={f.id || ""} onChange={set("id")} /></FormField>
          </Dialog>
          <Dialog header="Move AWS account" visible={dlg === "move"} onDismiss={close} submitLabel="Move AWS account"
            onSubmit={async () => { await api.moveAccount(acct.Id, acct.ParentId, f.dest.value); done(`Account ${acct.Name} moved.`); }}>
            <FormField label="Destination"><Select selectedOption={f.dest || null} options={parents} onChange={set("dest")} /></FormField>
          </Dialog>
        </SpaceBetween>
      );
    }}</OrgGate>
  );
}

const FEATURES = [
  ["RootCredentialsManagement", "Root credentials management", "Remove and prevent recovery of member-account root credentials."],
  ["RootSessions", "Root sessions", "Allow privileged root actions on member accounts via short-lived root sessions."],
];

/** Enable/disable the centralized-root-access features (real IAM API); enabling first turns on trusted access. */
export function RootFeaturesPanel({ model, onChange }) {
  const notify = useNotify();
  const feats = useAsync(() => api.listOrganizationsFeatures(), [model.data?.org?.Id]);
  const delegated = useAsync(() => (model.data?.org ? api.listDelegatedAdmins(IAM_SP) : Promise.resolve([])), [model.data?.org?.Id]);
  const on = feats.data || [];
  const flip = async (feature, enable) => {
    try {
      if (enable) await api.enableServiceAccess(IAM_SP);
      await api.setOrganizationsFeature(feature, enable);
      notify.success(`${enable ? "Enabled" : "Disabled"} ${feature === "RootSessions" ? "root sessions" : "root credentials management"}.`);
      feats.reload(); onChange?.();
    } catch (e) { notify.error(e); }
  };
  return (
    <CapabilityContainer id="iam.organizations.root-access" title="Centralized root access for member accounts"
      actions={<Button onClick={() => navigate("iam", "account-settings", "assign-delegated-administrator")}>Assign delegated administrator</Button>}>
      <SpaceBetween size="m">
        {FEATURES.map(([key, label, desc]) => (
          <Toggle key={key} checked={on.includes(key)} onChange={({ detail }) => flip(key, detail.checked)} description={desc}>{label}</Toggle>
        ))}
        <Box>
          <Box variant="awsui-key-label">Delegated administrator</Box>
          <div>{(delegated.data || []).map((a) => `${a.Name} (${a.Id})`).join(", ") || "None"}</div>
        </Box>
      </SpaceBetween>
    </CapabilityContainer>
  );
}

export function RootAccessManagement() {
  const notify = useNotify();
  const model = useOrgModel();
  const feats = useAsync(() => api.listOrganizationsFeatures(), [model.data?.org?.Id]);
  const on = feats.data || [];
  return (
    <OrgGate model={model} title="Root access management">{(m) => (
      <SpaceBetween size="l">
        <RootFeaturesPanel model={model} onChange={feats.reload} />
        <OrgStructure m={m} title="Member accounts"
          actions={<Button onClick={() => notify.error({ code: "NotSupported", message: "Take privileged action needs sts:AssumeRoot into a member account's root session; member accounts have no resources or credentials in Vyomi." })}>Take privileged action</Button>}
          extraCols={[
            { id: "creds", header: "Root credentials management", cell: (a) => (a.Id === m.org.MasterAccountId ? "Not applicable" : on.includes("RootCredentialsManagement") ? "Enabled" : "Disabled") },
            { id: "sess", header: "Root sessions", cell: (a) => (a.Id === m.org.MasterAccountId ? "Not applicable" : on.includes("RootSessions") ? "Enabled" : "Disabled") },
          ]} />
      </SpaceBetween>
    )}</OrgGate>
  );
}

export function AssignDelegatedAdministrator() {
  const notify = useNotify();
  const model = useOrgModel();
  const [acct, setAcct] = useState(null);
  const [busy, setBusy] = useState(false);
  const delegated = useAsync(() => (model.data?.org ? api.listDelegatedAdmins(IAM_SP) : Promise.resolve([])), [model.data?.org?.Id]);
  return (
    <OrgGate model={model} title="Assign delegated administrator for centralized root access">{(m) => (
      <SpaceBetween size="l">
        <CapabilityContainer id="iam.organizations.root-access" title="Assign delegated administrator for centralized root access"
          actions={<Button variant="primary" loading={busy} disabled={!acct} onClick={async () => {
            setBusy(true);
            try {
              await api.enableServiceAccess(IAM_SP);
              await api.registerDelegatedAdmin(acct.value, IAM_SP);
              notify.success(`Account ${acct.value} is now the delegated administrator for centralized root access.`);
              setAcct(null); delegated.reload();
            } catch (e) { notify.error(e); } finally { setBusy(false); }
          }}>Assign</Button>}>
          <FormField label="AWS account ID" description="A member account of the organization (not the management account).">
            <Select selectedOption={acct} onChange={({ detail }) => setAcct(detail.selectedOption)} placeholder="Choose an account"
              ariaLabel="AWS account ID"
              options={m.accounts.filter((a) => a.Id !== m.org.MasterAccountId && a.Status === "ACTIVE").map((a) => opt(a.Id, `${a.Name} (${a.Id})`))}
              empty="No member accounts - create one in Account access manager" />
          </FormField>
        </CapabilityContainer>
        <Table variant="container" items={delegated.data || []} loading={delegated.loading} trackBy="Id"
          header={<Header variant="h2" counter={`(${(delegated.data || []).length})`}>Delegated administrators</Header>}
          columnDefinitions={[
            { id: "name", header: "Account", isRowHeader: true, cell: (a) => a.Name },
            { id: "id", header: "Account ID", cell: (a) => a.Id },
            { id: "since", header: "Delegated since", cell: (a) => fmtDate(a.DelegationEnabledDate) },
            { id: "act", header: "Actions", cell: (a) => <Button variant="inline-link" onClick={async () => { try { await api.deregisterDelegatedAdmin(a.Id, IAM_SP); notify.success("Delegated administrator removed."); delegated.reload(); } catch (e) { notify.error(e); } }}>Remove</Button> },
          ]}
          empty={<Box textAlign="center"><b>No delegated administrator</b></Box>} />
      </SpaceBetween>
    )}</OrgGate>
  );
}

/** Account settings' "Centralized root access" panel (own model, so it works on a bare account). */
export function CentralizedRootAccessPanel() {
  const model = useOrgModel();
  if (model.loading) return null;
  if (!model.data?.org) {
    return <CapabilityContainer id="iam.organizations.root-access" title="Centralized root access for member accounts">
      <Box color="text-body-secondary">This account is not in an organization. <Button variant="inline-link" onClick={() => navigate("iam", "root-access-management")}>Set up an organization</Button></Box>
    </CapabilityContainer>;
  }
  return <RootFeaturesPanel model={model} />;
}
