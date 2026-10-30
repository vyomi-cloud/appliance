/* Secret detail — General details + 5 tabs, all wired to real secretsmanager.* calls except
 * Replication (core/capabilities/aws/secretsmanager.json: secretsmanager.secret.replication,
 * not_simulated — there's no second Region's store to replicate into). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Alert from "@cloudscape-design/components/alert";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import Toggle from "@cloudscape-design/components/toggle";
import Spinner from "@cloudscape-design/components/spinner";
import SpaceBetween from "@cloudscape-design/components/space-between";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate, href, follow } from "../../../common/router.js";
import { ErrorAlert, fmtDate, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

function SecretValueSection({ name }) {
  const notify = useNotify();
  const [revealed, setRevealed] = useState(null);
  const [busy, setBusy] = useState(false);
  const retrieve = async () => {
    setBusy(true);
    try { setRevealed(await api.getSecretValue(name)); }
    catch (e) { notify.error(e); }
    finally { setBusy(false); }
  };
  const kv = revealed ? api.asKeyValue(revealed.SecretString) : null;
  return (
    <Container header={<Header variant="h2" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button loading={busy} onClick={retrieve}>Retrieve secret value</Button>
        <Button href={href("secretsmanager", "secret", name, "edit-value")} onFollow={follow}>Edit</Button>
      </SpaceBetween>
    }>Secret value</Header>}>
      <FormField label="Key/value" stretch>
        {!revealed ? (
          <Box color="text-body-secondary">•••••••• — choose "Retrieve secret value" to view.</Box>
        ) : kv ? (
          <Table variant="embedded" items={kv} columnDefinitions={[{ id: "k", header: "Secret key", cell: (r) => r.key }, { id: "v", header: "Secret value", cell: (r) => r.value }]} />
        ) : (
          <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{revealed.SecretString ?? `(binary, ${revealed.SecretBinary?.length || 0} bytes base64)`}</pre></Box>
        )}
      </FormField>
    </Container>
  );
}

function OverviewTab({ name }) {
  return (
    <SpaceBetween size="l">
      <NotSimulatedContainer title="Resource permissions - optional" feature="IAM-principal permissions summary"
        note="The visual summary of who can access this secret isn't modeled; edit the resource policy JSON directly (Secrets list page action, or the create wizard's Resource permissions step)." />
      <SecretValueSection name={name} />
    </SpaceBetween>
  );
}

function RotationTab({ name, secret, reload }) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState(null);
  const rotateNow = async () => {
    setBusy(true);
    try { await api.rotateSecret(name, { RotateImmediately: true }); notify.success("Secret rotated — a new version is now AWSCURRENT."); reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  const save = async () => {
    setBusy(true);
    try {
      await api.rotateSecret(name, { RotationRules: { AutomaticallyAfterDays: edit.days }, RotateImmediately: edit.now });
      notify.success("Rotation configured.");
      setEdit(null); reload();
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={() => setEdit({ days: secret.RotationRules?.AutomaticallyAfterDays || 30, now: true })}>Edit rotation</Button>
          <Button loading={busy} disabled={!secret.RotationEnabled} onClick={rotateNow}>Rotate secret immediately</Button>
        </SpaceBetween>
      }>Rotation configuration</Header>}>
        <KeyValue columns={2} items={[
          ["Rotation status", secret.RotationEnabled ? "Enabled" : "Disabled"],
          ["Rotation schedule", secret.RotationRules ? JSON.stringify(secret.RotationRules) : "-"],
          ["Last rotated date (UTC)", secret.LastRotatedDate ? fmtDate(secret.LastRotatedDate) : "-"],
          ["Next rotation date (UTC)", secret.RotationEnabled ? "Vyomi rotates on demand only — there's no background scheduler." : "-"],
          ["Lambda rotation function", "Not simulated — no Lambda runtime wired to Secrets Manager."],
        ]} />
      </Container>
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header="Edit rotation"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={save}>Save</Button>
        </SpaceBetween></Box>}>
        {edit && (
          <SpaceBetween size="m">
            <FormField label="Rotate every">
              <Select selectedOption={{ label: `${edit.days} days`, value: String(edit.days) }}
                onChange={({ detail }) => setEdit({ ...edit, days: Number(detail.selectedOption.value) })}
                options={[7, 30, 60, 90].map((d) => ({ label: `${d} days`, value: String(d) }))} />
            </FormField>
            <Toggle checked={edit.now} onChange={({ detail }) => setEdit({ ...edit, now: detail.checked })}>Rotate immediately when saved</Toggle>
          </SpaceBetween>
        )}
      </Modal>
    </SpaceBetween>
  );
}

function VersionsTab({ name }) {
  const v = useAsync(() => api.listSecretVersionIds(name), [name]);
  return (
    <Table variant="container" header={<Header variant="h2" counter={`(${(v.data || []).length})`}>Versions</Header>}
      items={v.data || []} loading={v.loading}
      columnDefinitions={[
        { id: "id", header: "Version ID", cell: (r) => r.VersionId },
        { id: "stages", header: "Staging labels", cell: (r) => (r.VersionStages || []).join(", ") || "-" },
        { id: "created", header: "Created on (UTC)", cell: (r) => fmtDate(r.CreatedDate) },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No versions</b></Box>} />
  );
}

function TagsTab({ name, tags, reload }) {
  const notify = useNotify();
  const [edit, setEdit] = useState(null);
  return (
    <Container header={<Header variant="h2" counter={`(${tags.length})`} actions={<Button onClick={() => setEdit(tags.map((t) => ({ key: t.Key, value: t.Value })))}>Edit tags</Button>}>Tags</Header>}>
      <Table variant="embedded" items={tags} columnDefinitions={[{ id: "k", header: "Key", cell: (t) => t.Key }, { id: "v", header: "Value", cell: (t) => t.Value || "-" }]}
        empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>} />
      <Modal visible={edit !== null} onDismiss={() => setEdit(null)} size="large" header="Edit tags"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            try {
              const current = new Set(tags.map((t) => t.Key));
              const next = new Set(edit.filter((x) => !x.markedForRemoval && x.key).map((x) => x.key));
              const toRemove = [...current].filter((k) => !next.has(k));
              if (toRemove.length) await api.untagResource(name, toRemove);
              const toAdd = edit.filter((x) => !x.markedForRemoval && x.key).map((x) => ({ Key: x.key, Value: x.value || "" }));
              if (toAdd.length) await api.tagResource(name, toAdd);
              notify.success("Tags updated."); setEdit(null); reload();
            } catch (e) { notify.error(e); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <TagEditor tags={edit} onChange={({ detail }) => setEdit(detail.tags)} />}
      </Modal>
    </Container>
  );
}

export default function SecretDetail({ params }) {
  const name = params.name;
  const notify = useNotify();
  const d = useAsync(() => api.describeSecret(name), [name]);
  if (d.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const secret = d.data;
  const pendingDeletion = !!secret.DeletedDate;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <ButtonDropdown items={[
        { id: "edit", text: "Edit secret value" },
        { id: "delete", text: "Delete secret", disabled: pendingDeletion },
        { id: "cancel", text: "Cancel secret deletion", disabled: !pendingDeletion },
      ]} onItemClick={async ({ detail }) => {
        if (detail.id === "edit") navigate("secretsmanager", "secret", name, "edit-value");
        else if (detail.id === "delete") navigate("secretsmanager", "secret", name, "delete");
        else if (detail.id === "cancel") { try { await api.restoreSecret(name); notify.success("Secret deletion canceled."); d.reload(); } catch (e) { notify.error(e); } }
      }}>Actions</ButtonDropdown>
    }>{name}</Header>}>
      <SpaceBetween size="l">
        {pendingDeletion && <Alert type="warning">This secret is scheduled for deletion on {fmtDate(secret.DeletedDate)}.</Alert>}
        <KeyValue title="Secret details" columns={4} items={[
          ["Encryption key", secret.KmsKeyId], ["Secret name", secret.Name], ["Secret ARN", secret.ARN], ["Secret description", secret.Description],
        ]} />
        <Tabs tabs={[
          { id: "overview", label: "Overview", content: <OverviewTab name={name} /> },
          { id: "rotation", label: "Rotation", content: <RotationTab name={name} secret={secret} reload={d.reload} /> },
          { id: "versions", label: "Versions", content: <VersionsTab name={name} /> },
          { id: "replication", label: "Replication", content: <NotSimulatedContainer title="Replicate secret"
            note="Creating read-only replicas of this secret in other AWS Regions isn't modeled — there's no second Region's store to replicate into." /> },
          { id: "tags", label: "Tags", content: <TagsTab name={name} tags={secret.Tags || []} reload={d.reload} /> },
        ]} />
      </SpaceBetween>
    </ContentLayout>
  );
}
