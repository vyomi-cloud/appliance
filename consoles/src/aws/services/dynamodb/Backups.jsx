import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Container from "@cloudscape-design/components/container";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import TagEditor from "@cloudscape-design/components/tag-editor";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue, fmtBytes, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

function CreateBackupModal({ visible, onDismiss, onCreated, tables, presetTable }) {
  const notify = useNotify();
  const [table, setTable] = useState(presetTable || "");
  const [mode, setMode] = useState("Default settings");
  const [name, setName] = useState("");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const autoName = table ? `${table}-backup-${Date.now() % 100000}` : "";

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createBackup(table, mode === "Customize settings" && name ? name : autoName);
      notify.success(`Creating backup for "${table}".`);
      onCreated(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} size="medium" onDismiss={onDismiss} header="Create on-demand backup"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!table} onClick={submit}>Create backup</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <Container header={<Header variant="h3">Source table</Header>}>
          <FormField label="Source table">
            <Select selectedOption={table ? { value: table, label: table } : null}
              options={tables.map((t) => ({ value: t, label: t }))}
              onChange={({ detail }) => setTable(detail.selectedOption.value)} placeholder="Choose a table" ariaLabel="Source table" />
          </FormField>
        </Container>
        <Container header={<Header variant="h3">Backup settings</Header>}>
          <SpaceBetween size="l">
            <FormField label="Backup settings">
              <RadioGroup value={mode} onChange={({ detail }) => setMode(detail.value)}
                items={[{ value: "Default settings", label: "Default settings" }, { value: "Customize settings", label: "Customize settings" }]} />
            </FormField>
            {mode === "Customize settings" && (
              <FormField label="Backup name" constraintText="A backup name will be created automatically.">
                <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder={autoName} ariaLabel="Backup name" />
              </FormField>
            )}
            <KeyValue columns={2} items={[["Backup window", "Start in 1 hour"], ["Backup management", "AWS Backup"],
              ["Transition to cold storage", "Never"], ["Retention period", "Always"],
              ["Backup vault", "Default"], ["IAM Role", "AWSBackupDefaultServiceRole"]]} />
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h3">Tags - optional</Header>}>
          <FormField label="Tags">
            <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={{
              keyHeader: "Key", valueHeader: "Value - optional", addButton: "Add new tag", removeButton: "Remove",
              undoButton: "Undo", undoPrompt: "This tag will be removed upon saving changes", loading: "Loading tags",
              keyPlaceholder: "Enter key", valuePlaceholder: "Enter value", emptyTags: "No tags are associated with the resource.",
            }} />
          </FormField>
        </Container>
      </SpaceBetween>
    </Modal>
  );
}

function RestoreModal({ backup, onDismiss, onDone }) {
  const notify = useNotify();
  const [target, setTarget] = useState(backup ? `${backup.TableName}-restored` : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.restoreTableFromBackup(backup.BackupArn, target);
      notify.success(`Restoring "${target}" from backup "${backup.BackupName}".`);
      onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={!!backup} onDismiss={onDismiss} header="Restore backup"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!target} onClick={submit}>Restore backup</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="New table name" description={`Restores a copy of "${backup?.BackupName}" into a new table.`}>
          <Input value={target} onChange={({ detail }) => setTarget(detail.value)} ariaLabel="New table name" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function DetailsModal({ arn, onDismiss }) {
  const d = useAsync(() => (arn ? api.describeBackup(arn) : Promise.resolve(null)), [arn]);
  return (
    <Modal visible={!!arn} onDismiss={onDismiss} size="large" header="Backup details"
      footer={<Box float="right"><Button onClick={onDismiss}>Close</Button></Box>}>
      {d.loading ? "Loading…" : d.error ? <ErrorAlert error={d.error} /> : (
        <KeyValue columns={2} items={[
          ["Backup name", d.data?.BackupDetails?.BackupName], ["Status", d.data?.BackupDetails?.BackupStatus],
          ["Table", d.data?.SourceTableDetails?.TableName], ["Type", d.data?.BackupDetails?.BackupType],
          ["Size", fmtBytes(d.data?.BackupDetails?.BackupSizeBytes)], ["Item count", d.data?.SourceTableDetails?.ItemCount],
          ["Created", fmtDate(d.data?.BackupDetails?.BackupCreationDateTime)], ["ARN", d.data?.BackupDetails?.BackupArn],
        ]} />
      )}
    </Modal>
  );
}

export default function Backups() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const [restore, setRestore] = useState(null);
  const [details, setDetails] = useState(null);
  const backups = useAsync(() => api.listBackups(), []);
  const tables = useAsync(() => api.listTables(), []);

  return (
    <ContentLayout header={<Header variant="h1">Backups</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2" actions={
          <span data-vyomi-not-simulated="Turn off AWS Backup integration for DynamoDB"><Button disabled>Turn off</Button></span>
        }>Backup settings</Header>}>
          <KeyValue columns={1} items={[["Advanced features with AWS Backup", "Activated"]]} />
        </Container>

        <ResourceTable
          resourceName="Backups"
          items={backups.data || []}
          loading={backups.loading}
          error={backups.error}
          onRefresh={backups.reload}
          trackBy="BackupArn"
          selectionType="single"
          selectedItems={sel}
          onSelectionChange={setSel}
          columns={[
            { id: "name", header: "Name", isRowHeader: true, cell: (b) => b.BackupName },
            { id: "table", header: "Table", cell: (b) => b.TableName },
            { id: "status", header: "Status", cell: (b) => <StatusIndicator type={b.BackupStatus === "AVAILABLE" ? "success" : "in-progress"}>{b.BackupStatus}</StatusIndicator> },
            { id: "created", header: "Creation time", cell: (b) => fmtDate(b.BackupCreationDateTime) },
            { id: "arn", header: "ARN", cell: (b) => b.BackupArn },
            { id: "size", header: "Size", cell: (b) => fmtBytes(b.BackupSizeBytes) },
            { id: "type", header: "Type", cell: (b) => b.BackupType },
          ]}
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button disabled={sel.length !== 1} onClick={() => setDetails(sel[0].BackupArn)}>View details</Button>
              <Button disabled={sel.length !== 1} onClick={() => setRestore(sel[0])}>Restore</Button>
              <span data-vyomi-not-simulated="Copy a backup to another account or Region"><Button disabled>Copy</Button></span>
              <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
              <Button variant="primary" onClick={() => setCreate(true)}>Create backup</Button>
            </SpaceBetween>
          }
          empty={{ title: "No backups", subtitle: "You have not created any backups yet.", action: <Button onClick={() => setCreate(true)}>Create backup</Button> }}
        />
      </SpaceBetween>

      <CreateBackupModal visible={create} onDismiss={() => setCreate(false)} onCreated={backups.reload} tables={tables.data || []} />
      <RestoreModal backup={restore} onDismiss={() => setRestore(null)} onDone={backups.reload} />
      <DetailsModal arn={details} onDismiss={() => setDetails(null)} />
      <DeleteModal visible={del} resourceType="backup" names={sel.map((b) => b.BackupName)} confirmText="delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const b of sel) await api.deleteBackup(b.BackupArn); notify.success(`${sel.length} backup(s) deleted.`); setSel([]); backups.reload(); }} />
    </ContentLayout>
  );
}
