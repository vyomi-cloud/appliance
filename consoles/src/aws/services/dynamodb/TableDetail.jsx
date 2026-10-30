import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Toggle from "@cloudscape-design/components/toggle";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import { attrType, capacity, keyOf, statusOf, tableClass } from "./Tables.jsx";
import { getLayoutSettings, TABLE_TAB_ID } from "./prefs.js";
import * as api from "./api.js";

export default function TableDetail({ params, query }) {
  const name = params.name;
  const [tab, setTab] = useState(query.tab || TABLE_TAB_ID[getLayoutSettings().defaultTableTab] || "overview");
  const t = useAsync(() => api.describeTable(name), [name]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const d = t.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={t.reload} iconName="refresh" ariaLabel="Refresh" />
        <Button variant="primary" href={href("dynamodb", "tables", name, "items")} onFollow={follow}>Explore table items</Button>
      </SpaceBetween>
    }>{name}</Header>}>
      <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
        { id: "overview", label: "Overview", content: <Overview d={d} reload={t.reload} /> },
        { id: "indexes", label: "Indexes", content: <SpaceBetween size="l">
            <Indexes d={d} />
            <NotSimulatedContainer title="Local secondary indexes" feature="DynamoDB local secondary indexes" note="LSIs must be declared at table creation and aren't modeled; this table is always empty." />
          </SpaceBetween> },
        { id: "monitor", label: "Monitor", content: <SpaceBetween size="l">
            <NotSimulatedContainer title="CloudWatch alarms" feature="DynamoDB CloudWatch alarms" />
            <NotSimulatedContainer title="CloudWatch metrics" feature="DynamoDB CloudWatch metrics" />
          </SpaceBetween> },
        { id: "global-tables", label: "Global tables", content: <NotSimulatedContainer title="Replicas" feature="Global tables (multi-Region replicas)" /> },
        { id: "backups", label: "Backups", content: <Backups name={name} /> },
        { id: "exports", label: "Exports and streams", content: <SpaceBetween size="l">
            <NotSimulatedContainer title="Amazon Kinesis data stream details" feature="DynamoDB Kinesis data streaming" />
            <KeyValue title="DynamoDB stream details" columns={2} items={[["Stream status", d.StreamSpecification?.StreamEnabled ? "On" : "Off"], ["View type", d.StreamSpecification?.StreamViewType]]} />
            <NotSimulatedContainer title="Trigger" feature="DynamoDB stream triggers (Lambda)" />
          </SpaceBetween> },
        { id: "permissions", label: "Permissions", content: <NotSimulatedContainer title="Resource-based policy for table" /> },
        { id: "settings", label: "Additional settings", content: <Settings d={d} reload={t.reload} /> },
      ]} />
    </ContentLayout>
  );
}

function CapacityModal({ d, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [mode, setMode] = useState(capacity(d) === "On-demand" ? "PAY_PER_REQUEST" : "PROVISIONED");
  const [rcu, setRcu] = useState(String(d.ProvisionedThroughput?.ReadCapacityUnits || 5));
  const [wcu, setWcu] = useState(String(d.ProvisionedThroughput?.WriteCapacityUnits || 5));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.updateTable({ TableName: d.TableName, BillingMode: mode, ...(mode === "PROVISIONED" ? { ProvisionedThroughput: { ReadCapacityUnits: Number(rcu), WriteCapacityUnits: Number(wcu) } } : {}) });
      notify.success("Capacity settings updated."); onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Edit read/write capacity"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Save changes</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Capacity mode">
          <RadioGroup value={mode} onChange={({ detail }) => setMode(detail.value)}
            items={[{ value: "PAY_PER_REQUEST", label: "On-demand" }, { value: "PROVISIONED", label: "Provisioned" }]} />
        </FormField>
        {mode === "PROVISIONED" && (
          <SpaceBetween direction="horizontal" size="l">
            <FormField label="Read capacity units"><Input type="number" value={rcu} onChange={({ detail }) => setRcu(detail.value)} ariaLabel="Read capacity units" /></FormField>
            <FormField label="Write capacity units"><Input type="number" value={wcu} onChange={({ detail }) => setWcu(detail.value)} ariaLabel="Write capacity units" /></FormField>
          </SpaceBetween>
        )}
      </SpaceBetween>
    </Modal>
  );
}

function Overview({ d, reload }) {
  const notify = useNotify();
  const pitr = useAsync(() => api.describeBackups(d.TableName), [d.TableName]);
  const [capModal, setCapModal] = useState(false);
  const [protBusy, setProtBusy] = useState(false);
  const pk = keyOf(d, "HASH"), sk = keyOf(d, "RANGE");
  const pitrOn = pitr.data?.PointInTimeRecoveryDescription?.PointInTimeRecoveryStatus === "ENABLED";
  const toggleProtection = async () => {
    setProtBusy(true);
    try {
      await api.updateTable({ TableName: d.TableName, DeletionProtectionEnabled: !d.DeletionProtectionEnabled });
      notify.success(`Deletion protection turned ${d.DeletionProtectionEnabled ? "off" : "on"}.`);
      reload();
    } catch (e) { notify.error(e); } finally { setProtBusy(false); }
  };
  return (
    <SpaceBetween size="l">
      <KeyValue title="General information" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={() => setCapModal(true)}>Edit capacity</Button>
          <Button loading={protBusy} onClick={toggleProtection}>{d.DeletionProtectionEnabled ? "Turn off deletion protection" : "Turn on deletion protection"}</Button>
        </SpaceBetween>
      } columns={4} items={[
        ["Partition key", pk && `${pk} (${attrType(d, pk)})`], ["Sort key", sk ? `${sk} (${attrType(d, sk)})` : "-"],
        ["Capacity mode", capacity(d)], ["Table status", statusOf(d.TableStatus)],
        ["Alarms", "No active alarms"], ["Point-in-time recovery (PITR)", pitr.data === null ? "-" : (pitrOn ? "On" : "Off")],
        ["Item count", d.ItemCount ?? 0], ["Table size", `${d.TableSizeBytes ?? 0} bytes`],
        ["Amazon Resource Name (ARN)", d.TableArn], ["Creation date", fmtDate(d.CreationDateTime)], ["Deletion protection", d.DeletionProtectionEnabled ? "On" : "Off"],
        ["Table class", tableClass(d)],
      ]} />
      <CapacityModal d={d} visible={capModal} onDismiss={() => setCapModal(false)} onDone={reload} />
    </SpaceBetween>
  );
}

function Indexes({ d }) {
  const rows = d.GlobalSecondaryIndexes || [];
  return (
    <Table variant="container" header={<Header variant="h2" counter={`(${rows.length})`}>Global secondary indexes</Header>} items={rows}
      columnDefinitions={[
        { id: "n", header: "Name", cell: (i) => i.IndexName },
        { id: "s", header: "Status", cell: (i) => statusOf(i.IndexStatus || "ACTIVE") },
        { id: "pk", header: "Partition key", cell: (i) => i.KeySchema?.find((k) => k.KeyType === "HASH")?.AttributeName },
        { id: "sk", header: "Sort key", cell: (i) => i.KeySchema?.find((k) => k.KeyType === "RANGE")?.AttributeName || "-" },
        { id: "p", header: "Projected attributes", cell: (i) => i.Projection?.ProjectionType || "-" },
        { id: "sz", header: "Size", cell: () => `${d.TableSizeBytes ?? 0} bytes` },
        { id: "ic", header: "Item count", cell: (i) => i.ItemCount ?? 0 },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No global secondary indexes</b><Box variant="p" color="inherit">You have not created any global secondary indexes for this table.</Box></Box>} />
  );
}

function PitrModal({ name, enabled, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [on, setOn] = useState(enabled);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.updateContinuousBackups(name, on); notify.success(`Point-in-time recovery turned ${on ? "on" : "off"}.`); onDone(); onDismiss(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Edit point-in-time recovery (PITR)"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Save changes</Button></SpaceBetween></Box>}>
      {error && <ErrorAlert error={error} />}
      <Toggle checked={on} onChange={({ detail }) => setOn(detail.checked)}>Turn on point-in-time recovery</Toggle>
    </Modal>
  );
}

function CreateBackupModal({ name, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [backupName, setBackupName] = useState(`${name}-backup`);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.createBackup(name, backupName); notify.success(`Creating backup "${backupName}".`); onDone(); onDismiss(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create backup"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Create backup</Button></SpaceBetween></Box>}>
      {error && <ErrorAlert error={error} />}
      <FormField label="Backup name"><Input value={backupName} onChange={({ detail }) => setBackupName(detail.value)} ariaLabel="Backup name" /></FormField>
    </Modal>
  );
}

function Backups({ name }) {
  const notify = useNotify();
  const b = useAsync(() => api.describeBackups(name), [name]);
  const rows = useAsync(() => api.listBackups(name), [name]);
  const [sel, setSel] = useState([]);
  const [pitrModal, setPitrModal] = useState(false);
  const [createModal, setCreateModal] = useState(false);
  const [restoreTarget, setRestoreTarget] = useState("");
  const [restoring, setRestoring] = useState(null);
  const [del, setDel] = useState(false);
  if (b.loading) return <Spinner />;
  if (b.data === null) return <NotSimulatedContainer title="Point-in-time recovery (PITR)" />;
  const pitrOn = b.data?.PointInTimeRecoveryDescription?.PointInTimeRecoveryStatus === "ENABLED";
  return (
    <SpaceBetween size="l">
      <KeyValue title="Point-in-time recovery (PITR)" actions={<Button onClick={() => setPitrModal(true)}>Edit</Button>}
        columns={2} items={[["Status", pitrOn ? "On" : "Off"], ["Earliest restore date", fmtDate(b.data?.PointInTimeRecoveryDescription?.EarliestRestorableDateTime)]]} />
      <Table
        variant="container"
        items={rows.data || []}
        loading={rows.loading}
        trackBy="BackupArn"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h2" counter={`(${(rows.data || []).length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => { setRestoreTarget(`${name}-restored`); setRestoring(sel[0]); }}>Restore</Button>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => setCreateModal(true)}>Create backup</Button>
          </SpaceBetween>
        }>Backups</Header>}
        columnDefinitions={[
          { id: "name", header: "Name", cell: (x) => x.BackupName },
          { id: "status", header: "Status", cell: (x) => <StatusIndicator type={x.BackupStatus === "AVAILABLE" ? "success" : "in-progress"}>{x.BackupStatus}</StatusIndicator> },
          { id: "created", header: "Creation time", cell: (x) => fmtDate(x.BackupCreationDateTime) },
          { id: "size", header: "Size", cell: (x) => fmtBytes(x.BackupSizeBytes) },
          { id: "type", header: "Type", cell: (x) => x.BackupType },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No backups</b></Box>} />

      <PitrModal name={name} enabled={pitrOn} visible={pitrModal} onDismiss={() => setPitrModal(false)} onDone={b.reload} />
      <CreateBackupModal name={name} visible={createModal} onDismiss={() => setCreateModal(false)} onDone={rows.reload} />
      <Modal visible={!!restoring} onDismiss={() => setRestoring(null)} header="Restore backup"
        footer={<Box float="right"><Button variant="primary" disabled={!restoreTarget} onClick={async () => {
          try { await api.restoreTableFromBackup(restoring.BackupArn, restoreTarget); notify.success(`Restoring "${restoreTarget}" from backup "${restoring.BackupName}".`); setRestoring(null); }
          catch (e) { notify.error(e); }
        }}>Restore backup</Button></Box>}>
        <FormField label="New table name"><Input value={restoreTarget} onChange={({ detail }) => setRestoreTarget(detail.value)} ariaLabel="New table name" /></FormField>
      </Modal>
      <DeleteModal visible={del} resourceType="backup" names={sel.map((x) => x.BackupName)} confirmText="delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const x of sel) await api.deleteBackup(x.BackupArn); notify.success(`${sel.length} backup(s) deleted.`); setSel([]); rows.reload(); }} />
    </SpaceBetween>
  );
}

function TtlModal({ name, ttl, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [enabled, setEnabled] = useState(ttl?.TimeToLiveStatus === "ENABLED");
  const [attr, setAttr] = useState(ttl?.AttributeName || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.updateTtl(name, { AttributeName: attr, Enabled: enabled }); notify.success(`TTL turned ${enabled ? "on" : "off"}.`); onDone(); onDismiss(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Edit Time to Live (TTL)"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Save changes</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <Toggle checked={enabled} onChange={({ detail }) => setEnabled(detail.checked)}>Turn on TTL</Toggle>
        <FormField label="TTL attribute" description="A number attribute (epoch seconds) that marks when an item should expire.">
          <Input value={attr} onChange={({ detail }) => setAttr(detail.value)} disabled={!enabled} ariaLabel="TTL attribute" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function Settings({ d, reload }) {
  const ttl = useAsync(() => api.describeTtl(d.TableName), [d.TableName]);
  const tags = useAsync(() => api.tags(d.TableArn), [d.TableArn]);
  const [ttlModal, setTtlModal] = useState(false);
  return (
    <SpaceBetween size="l">
      <KeyValue title="Read/write capacity" columns={2} items={[["Capacity mode", capacity(d)], ["Read capacity", d.ProvisionedThroughput?.ReadCapacityUnits || "On-demand"], ["Write capacity", d.ProvisionedThroughput?.WriteCapacityUnits || "On-demand"]]} />
      {ttl.data === null ? <NotSimulatedContainer title="Time to Live (TTL)" /> : (
        <KeyValue title="Time to Live (TTL)" actions={<Button onClick={() => setTtlModal(true)}>{ttl.data?.TimeToLiveStatus === "ENABLED" ? "Turn off" : "Turn on"}</Button>}
          columns={2} items={[["TTL status", ttl.data?.TimeToLiveStatus === "ENABLED" ? "On" : "Off"], ["TTL attribute", ttl.data?.AttributeName]]} />
      )}
      <KeyValue title="Encryption" columns={2} items={[["Key management", d.SSEDescription?.SSEType === "KMS" ? "AWS managed key" : "Owned by Amazon DynamoDB"]]} />
      {tags.data === null ? <NotSimulatedContainer title="Tags" /> : (
        <Table variant="container" header={<Header variant="h2" counter={`(${tags.data?.length || 0})`}>Tags</Header>} items={tags.data || []} loading={tags.loading}
          columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.Key }, { id: "v", header: "Value", cell: (x) => x.Value || "-" }]}
          empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>} />
      )}
      {ttl.data !== null && <TtlModal name={d.TableName} ttl={ttl.data} visible={ttlModal} onDismiss={() => setTtlModal(false)} onDone={ttl.reload} />}
    </SpaceBetween>
  );
}
