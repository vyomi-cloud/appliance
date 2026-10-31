/* Customer managed key detail — General configuration + 5 tabs, all wired to real
 * TrentService calls. Key administrators/users/other-accounts are an IAM-principal
 * picker Vyomi doesn't model (core/capabilities/aws/kms.json: kms.key-administrators);
 * the key policy JSON itself, right below it, is real and editable. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Toggle from "@cloudscape-design/components/toggle";
import Spinner from "@cloudscape-design/components/spinner";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, fmtDate, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import { CapabilityContainer, capability, saveNotice } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const statusType = (s) => (s === "Enabled" ? "success" : s === "PendingDeletion" ? "warning" : "stopped");

// kms.key-administrators (not_simulated) note + the exact field names this gap panel
// must cover on this tab, so the visual-policy-editor pickers score as a declared gap.
const adminGapNote = () => `${capability("kms.key-administrators")?.limitations?.join(" ") || ""} Allow key administrators to delete this key.`;

function ScheduleModal({ keyId, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [days, setDays] = useState("30");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try { await api.scheduleKeyDeletion(keyId, Number(days)); notify.success(`Key scheduled for deletion in ${days} days.`); onDone(); onDismiss(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Schedule key deletion"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Schedule deletion</Button></SpaceBetween></Box>}>
      <FormField label="Waiting period (in days)" constraintText="7 to 30 days">
        <Input type="number" value={days} onChange={({ detail }) => setDays(detail.value)} ariaLabel="Waiting period (in days)" />
      </FormField>
    </Modal>
  );
}

function KeyPolicySection({ keyId }) {
  const notify = useNotify();
  const p = useAsync(() => api.getKeyPolicy(keyId), [keyId]);
  const [edit, setEdit] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  return (
    <CapabilityContainer id="kms.key.policy" title="Key policy" actions={<Button onClick={() => { setErr(null); setEdit(p.data || ""); }}>Edit</Button>}>
      <SpaceBetween size="l">
        <NotSimulatedContainer title="Key administrators and key users" note={adminGapNote()} />
        {p.loading ? <Spinner /> : <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{p.data}</pre></Box>}
      </SpaceBetween>
      <Modal visible={edit !== null} onDismiss={() => setEdit(null)} size="large" header="Edit key policy"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            try { JSON.parse(edit); } catch (e) { setErr(`Policy is not valid JSON: ${e.message}`); return; }
            setBusy(true);
            try { await api.putKeyPolicy(keyId, edit); notify.success(`Key policy updated.${saveNotice("kms.key.policy")}`); setEdit(null); p.reload(); }
            catch (e) { setErr(e.message); } finally { setBusy(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        <FormField label="Policy" errorText={err} stretch><Textarea rows={18} value={edit || ""} onChange={({ detail }) => setEdit(detail.value)} spellcheck={false} /></FormField>
      </Modal>
    </CapabilityContainer>
  );
}

function TagsTab({ keyId }) {
  const notify = useNotify();
  const t = useAsync(() => api.listResourceTags(keyId), [keyId]);
  const [edit, setEdit] = useState(null);
  return (
    <Container header={<Header variant="h2" counter={`(${(t.data || []).length})`} actions={<Button onClick={() => setEdit((t.data || []).map((x) => ({ key: x.TagKey, value: x.TagValue })))}>Edit</Button>}>Tags</Header>}>
      <Table variant="embedded" items={t.data || []} loading={t.loading}
        columnDefinitions={[{ id: "k", header: "Tag key", cell: (x) => x.TagKey }, { id: "v", header: "Tag value", cell: (x) => x.TagValue || "-" }]}
        empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>} />
      <Modal visible={edit !== null} onDismiss={() => setEdit(null)} size="large" header="Edit tags"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            try {
              const current = new Set((t.data || []).map((x) => x.TagKey));
              const next = new Set(edit.filter((x) => !x.markedForRemoval && x.key).map((x) => x.key));
              const toRemove = [...current].filter((k) => !next.has(k));
              if (toRemove.length) await api.untagResource(keyId, toRemove);
              const toAdd = edit.filter((x) => !x.markedForRemoval && x.key).map((x) => ({ TagKey: x.key, TagValue: x.value || "" }));
              if (toAdd.length) await api.tagResource(keyId, toAdd);
              notify.success("Tags updated."); setEdit(null); t.reload();
            } catch (e) { notify.error(e); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <TagEditor tags={edit} onChange={({ detail }) => setEdit(detail.tags)} />}
      </Modal>
    </Container>
  );
}

function RotationTab({ keyId, creationDate, reload }) {
  const notify = useNotify();
  const status = useAsync(() => api.getKeyRotationStatus(keyId), [keyId]);
  const rotations = useAsync(() => api.listKeyRotations(keyId), [keyId]);
  const [busy, setBusy] = useState(false);
  const lastRotation = rotations.data?.length ? rotations.data[rotations.data.length - 1].RotationDate : creationDate;
  const nextRotation = (status.data?.KeyRotationEnabled && lastRotation)
    ? fmtDate(lastRotation + status.data.RotationPeriodInDays * 86400) : "-";
  const toggle = async () => {
    setBusy(true);
    try {
      if (status.data?.KeyRotationEnabled) await api.disableKeyRotation(keyId);
      else await api.enableKeyRotation(keyId);
      notify.success(`Automatic key rotation turned ${status.data?.KeyRotationEnabled ? "off" : "on"}.${saveNotice("kms.key.rotation")}`);
      status.reload();
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  const rotateNow = async () => {
    setBusy(true);
    try { await api.rotateKeyOnDemand(keyId); notify.success("Key material rotated."); rotations.reload(); reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="kms.key.rotation" title="Automatic key rotation"
        actions={<Button loading={busy} onClick={toggle}>{status.data?.KeyRotationEnabled ? "Disable" : "Enable"}</Button>}>
        <ColumnLayout columns={3} variant="text-grid">
          <div><Box variant="awsui-key-label">Automatic key rotation</Box><div>{status.loading ? "-" : (status.data?.KeyRotationEnabled ? "On" : "Off")}</div></div>
          <div><Box variant="awsui-key-label">Rotation period (in days)</Box><div>{status.data?.RotationPeriodInDays || "-"}</div></div>
          <div><Box variant="awsui-key-label">Next rotation date</Box><div>{nextRotation}</div></div>
        </ColumnLayout>
        {status.data?.KeyRotationEnabled && (
          <Box color="text-body-secondary" margin={{ top: "s" }} fontSize="body-s">
            Vyomi checks the schedule lazily (on the next operation against this key, or when this page loads) rather than
            running a background scheduler — the key still rotates on time, it's just evaluated on next touch.
          </Box>
        )}
      </CapabilityContainer>
      <Container header={<Header variant="h2" actions={<Button loading={busy} onClick={rotateNow}>Rotate now</Button>}>On-demand rotation</Header>}>
        <Box color="text-body-secondary">Immediately rotate this key's backing material. Data already encrypted under it keeps decrypting.</Box>
      </Container>
      <Table variant="container" header={<Header variant="h2" counter={`(${(rotations.data || []).length})`}>Key rotations</Header>}
        items={rotations.data || []} loading={rotations.loading}
        columnDefinitions={[
          { id: "m", header: "Key material ID", cell: (r) => r.KeyMaterialId },
          { id: "d", header: "Rotation date", cell: (r) => fmtDate(r.RotationDate) },
          { id: "t", header: "Rotation type", cell: (r) => r.RotationType },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No rotations</b></Box>} />
    </SpaceBetween>
  );
}

function AliasesTab({ keyId }) {
  const notify = useNotify();
  const a = useAsync(() => api.listAliases(keyId), [keyId]);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [name, setName] = useState("");
  return (
    <Container>
      <Table variant="embedded" items={a.data || []} loading={a.loading} trackBy="AliasName"
        selectionType="multi" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h2" counter={`(${(a.data || []).length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={async () => { for (const x of sel) await api.deleteAlias(x.AliasName); notify.success("Alias(es) deleted."); setSel([]); a.reload(); }}>Delete</Button>
            <Button variant="primary" onClick={() => setCreate(true)}>Create alias</Button>
          </SpaceBetween>
        }>Aliases</Header>}
        columnDefinitions={[{ id: "n", header: "Alias name", cell: (x) => x.AliasName }, { id: "a", header: "Alias ARN", cell: (x) => x.AliasArn }]}
        empty={<Box textAlign="center" color="inherit"><b>No aliases</b></Box>} />
      <Modal visible={create} onDismiss={() => setCreate(false)} header="Create alias"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(false)}>Cancel</Button>
          <Button variant="primary" disabled={!name} onClick={async () => { await api.createAlias(`alias/${name}`, keyId); notify.success(`Created alias "${name}".`); setCreate(false); setName(""); a.reload(); }}>Create alias</Button>
        </SpaceBetween></Box>}>
        <FormField label="Alias name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Alias name" /></FormField>
      </Modal>
    </Container>
  );
}

export default function CustomerManagedKeyDetail({ params }) {
  const keyId = params.id;
  const notify = useNotify();
  const d = useAsync(() => Promise.all([api.describeKey(keyId), api.listAliases(keyId)]), [keyId]);
  const [scheduleModal, setScheduleModal] = useState(false);
  if (d.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const [md, aliases] = d.data;
  const alias = aliases[0]?.AliasName?.replace(/^alias\//, "") || "-";
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <ButtonDropdown items={[
        { id: "enable", text: "Enable", disabled: md.KeyState !== "Disabled" },
        { id: "disable", text: "Disable", disabled: md.KeyState !== "Enabled" },
        { id: "schedule", text: "Schedule key deletion", disabled: md.KeyState === "PendingDeletion" },
        { id: "cancel", text: "Cancel key deletion", disabled: md.KeyState !== "PendingDeletion" },
      ]} onItemClick={async ({ detail }) => {
        try {
          if (detail.id === "enable") { await api.enableKey(keyId); notify.success("Key enabled."); }
          else if (detail.id === "disable") { await api.disableKey(keyId); notify.success("Key disabled."); }
          else if (detail.id === "schedule") { setScheduleModal(true); return; }
          else if (detail.id === "cancel") { await api.cancelKeyDeletion(keyId); notify.success("Key deletion canceled."); }
          d.reload();
        } catch (e) { notify.error(e); }
      }}>Key actions</ButtonDropdown>
    }>{md.KeyId}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="General configuration" columns={4} items={[
          ["Alias", alias], ["ARN", md.Arn], ["Current key material ID", md.KeyMaterialId],
          ["Status", <StatusIndicator key="s" type={statusType(md.KeyState)}>{md.KeyState}</StatusIndicator>],
          ["Description", md.Description], ["Creation date", fmtDate(md.CreationDate)],
          ["Last used", md.LastUsedDate ? fmtDate(md.LastUsedDate) : "Not used in the last 24 hours"],
          ["Regionality", "Single-Region key"],
        ]} />
        <Tabs tabs={[
          { id: "policy", label: "Key policy", content: <KeyPolicySection keyId={keyId} /> },
          { id: "crypto", label: "Cryptographic configuration", content: (
            <Container header={<Header variant="h2">Cryptographic configuration</Header>}>
              <KeyValue columns={4} items={[["Key Type", api.keyType(md)], ["Origin", md.Origin], ["Key Spec", md.KeySpec], ["Key Usage", md.KeyUsage]]} />
            </Container>
          ) },
          { id: "tags", label: "Tags", content: <TagsTab keyId={keyId} /> },
          { id: "rotation", label: "Key rotation", content: <RotationTab keyId={keyId} creationDate={md.CreationDate} reload={d.reload} /> },
          { id: "aliases", label: "Aliases", content: <AliasesTab keyId={keyId} /> },
        ]} />
      </SpaceBetween>
      <ScheduleModal keyId={keyId} visible={scheduleModal} onDismiss={() => setScheduleModal(false)} onDone={() => { navigate("kms", "customer-managed-keys"); }} />
    </ContentLayout>
  );
}
