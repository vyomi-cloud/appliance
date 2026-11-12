/* RDS > database > Data migrations: real AWS DMS (core/dms_core.py) between simulator RDS instances.
 * "Migrate to another database" creates (or reuses) a replication instance, the source/target endpoints, tests both connections
 * and creates + starts a replication task; the table is then really copied (full load) and, for CDC, kept in sync (polled). */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Select from "@cloudscape-design/components/select";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import { awsJson } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const dms = (action, payload) => awsJson("dms", `AmazonDMSv20160101.${action}`, payload, { version: "1.1" });
const RI_ID = "vyomi-dms-ri";

async function ensureEndpoint(id, type, db) {
  const have = (await dms("DescribeEndpoints", { Filters: [{ Name: "endpoint-id", Values: [id] }] })).Endpoints[0];
  if (have) return have.EndpointArn;
  const eng = String(db.Engine || "postgres").startsWith("mysql") ? "mysql" : String(db.Engine).startsWith("mariadb") ? "mariadb" : "postgres";
  const r = await dms("CreateEndpoint", {
    EndpointIdentifier: id, EndpointType: type, EngineName: eng, ServerName: db.Endpoint?.Address || db.DBInstanceIdentifier,
    Port: db.Endpoint?.Port || 5432, DatabaseName: db.DBName || "postgres", Username: db.MasterUsername || "admin", Password: "unused",
  });
  return r.Endpoint.EndpointArn;
}

export async function migrate(srcDb, tgtDb, migrationType, tablePattern, taskId) {
  let ri = (await dms("DescribeReplicationInstances", { Filters: [{ Name: "replication-instance-id", Values: [RI_ID] }] })).ReplicationInstances[0];
  if (!ri) ri = (await dms("CreateReplicationInstance", { ReplicationInstanceIdentifier: RI_ID, ReplicationInstanceClass: "dms.t3.micro" })).ReplicationInstance;
  const src = await ensureEndpoint(`src-${srcDb.DBInstanceIdentifier}`, "source", srcDb);
  const tgt = await ensureEndpoint(`tgt-${tgtDb.DBInstanceIdentifier}`, "target", tgtDb);
  for (const e of [src, tgt]) {
    const c = (await dms("TestConnection", { ReplicationInstanceArn: ri.ReplicationInstanceArn, EndpointArn: e })).Connection;
    if (c.Status !== "successful") throw new Error(c.LastFailureMessage || "Endpoint connection test failed");
  }
  const mappings = JSON.stringify({ rules: [{ "rule-type": "selection", "rule-id": "1", "rule-name": "1",
    "object-locator": { "schema-name": "%", "table-name": tablePattern || "%" }, "rule-action": "include" }] });
  const t = (await dms("CreateReplicationTask", { ReplicationTaskIdentifier: taskId, SourceEndpointArn: src, TargetEndpointArn: tgt,
    ReplicationInstanceArn: ri.ReplicationInstanceArn, MigrationType: migrationType, TableMappings: mappings })).ReplicationTask;
  return (await dms("StartReplicationTask", { ReplicationTaskArn: t.ReplicationTaskArn, StartReplicationTaskType: "start-replication" })).ReplicationTask;
}

function MigrateModal({ db, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const others = useAsync(async () => (await api.describeDBInstances()).filter((d) => d.DBInstanceIdentifier !== db.DBInstanceIdentifier), [db.DBInstanceIdentifier]);
  const [target, setTarget] = useState(null);
  const [type, setType] = useState({ value: "full-load", label: "Migrate existing data (full-load)" });
  const [tables, setTables] = useState("%");
  const [name, setName] = useState(`migrate-${db.DBInstanceIdentifier}`);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const go = async () => {
    setBusy(true); setErr(null);
    try {
      const tdb = (others.data || []).find((d) => d.DBInstanceIdentifier === target?.value);
      const t = await migrate(db, tdb, type.value, tables, name);
      notify.success?.(`Replication task ${t.ReplicationTaskIdentifier} is ${t.Status}.`);
      onDone(); onDismiss();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Migrate to another database"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!target || !name} onClick={go}>Start migration</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">
        {err && <ErrorAlert error={err} />}
        <FormField label="Target database" description="Another RDS instance in this simulator.">
          <Select selectedOption={target} onChange={({ detail }) => setTarget(detail.selectedOption)} statusType={others.loading ? "loading" : "finished"}
            options={(others.data || []).map((d) => ({ value: d.DBInstanceIdentifier, label: d.DBInstanceIdentifier, description: d.Engine }))}
            placeholder="Choose a database" />
        </FormField>
        <FormField label="Migration type">
          <Select selectedOption={type} onChange={({ detail }) => setType(detail.selectedOption)} options={[
            { value: "full-load", label: "Migrate existing data (full-load)" },
            { value: "full-load-and-cdc", label: "Migrate existing data and replicate ongoing changes (full-load-and-cdc)" },
            { value: "cdc", label: "Replicate data changes only (cdc)" }]} />
        </FormField>
        <FormField label="Table name pattern" description="% is a wildcard, as in DMS selection rules."><Input value={tables} onChange={({ detail }) => setTables(detail.value)} /></FormField>
        <FormField label="Task identifier"><Input value={name} onChange={({ detail }) => setName(detail.value)} /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function DataMigrations({ db }) {
  const [modal, setModal] = useState(false);
  const [sel, setSel] = useState([]);
  const notify = useNotify();
  const tasks = useAsync(async () => {
    const [ts, eps] = await Promise.all([dms("DescribeReplicationTasks", {}), dms("DescribeEndpoints", {})]);
    const host = (a) => (eps.Endpoints.find((e) => e.EndpointArn === a) || {}).ServerName;
    const mine = [db.DBInstanceIdentifier, db.Endpoint?.Address];
    return ts.ReplicationTasks.filter((t) => mine.includes(host(t.SourceEndpointArn)) || mine.includes(host(t.TargetEndpointArn)))
      .map((t) => ({ ...t, source: host(t.SourceEndpointArn), target: host(t.TargetEndpointArn) }));
  }, [db.DBInstanceIdentifier]);
  const act = async (action, extra = {}) => {
    try {
      for (const t of sel) await dms(action, { ReplicationTaskArn: t.ReplicationTaskArn, ...extra });
      setSel([]); tasks.reload();
    } catch (e) { notify.error?.(e.message); }
  };
  return (
    <CapabilityContainer id="rds.data-migrations" title="Data migrations">
      <SpaceBetween size="m">
        {tasks.error && <ErrorAlert error={tasks.error} />}
        <Table variant="container" selectionType="multi" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
          items={tasks.data || []} loading={tasks.loading} trackBy="ReplicationTaskIdentifier"
          header={<Header variant="h2" counter={`(${(tasks.data || []).length})`} actions={<SpaceBetween direction="horizontal" size="xs">
            <Button iconName="refresh" onClick={tasks.reload} />
            <Button disabled={sel.length === 0} onClick={() => act("StartReplicationTask", { StartReplicationTaskType: "resume-processing" })}>Resume</Button>
            <Button disabled={sel.length === 0} onClick={() => act("StopReplicationTask")}>Stop</Button>
            <Button disabled={sel.length === 0} onClick={() => act("DeleteReplicationTask")}>Delete</Button>
            <Button variant="primary" onClick={() => setModal(true)}>Migrate to another database</Button></SpaceBetween>}>Database migration tasks</Header>}
          columnDefinitions={[
            { id: "id", header: "Task", cell: (t) => t.ReplicationTaskIdentifier },
            { id: "status", header: "Status", cell: (t) => t.Status },
            { id: "type", header: "Migration type", cell: (t) => t.MigrationType },
            { id: "src", header: "Source", cell: (t) => t.source || "-" },
            { id: "tgt", header: "Target", cell: (t) => t.target || "-" },
            { id: "prog", header: "Progress", cell: (t) => `${t.ReplicationTaskStats?.FullLoadProgressPercent ?? 0}% (${t.ReplicationTaskStats?.TablesLoaded ?? 0} tables)` },
            { id: "why", header: "Stop reason / failure", cell: (t) => t.LastFailureMessage || t.StopReason || "-" }]}
          empty={<Box textAlign="center" color="inherit"><b>No migration tasks</b><Box variant="p" color="inherit">Migrate this database to another simulator database.</Box></Box>} />
      </SpaceBetween>
      <MigrateModal db={db} visible={modal} onDismiss={() => setModal(false)} onDone={tasks.reload} />
    </CapabilityContainer>
  );
}
