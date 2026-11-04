/* Zero-ETL integrations over the native wire: Glue CreateIntegration / DescribeIntegrations / DeleteIntegration
 * (DynamoDB sources), RDS CreateIntegration (RDS sources), and the Redshift Data API against the Vyomi "Redshift-lite"
 * warehouse the integrations replicate into. Shared by the DynamoDB "Integrations" and RDS "Zero-ETL integrations" pages. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import { awsJson, awsQuery, asList } from "../../common/wire.js";
import { useAsync } from "../../common/useAsync.js";
import { useNotify } from "../../common/notify.jsx";
import { CapabilityBadge } from "./Capability.jsx";
import { ErrorAlert } from "./common.jsx";

const ACCT = "123456789012";
const glue = (op, body) => awsJson("glue", `AWSGlue.${op}`, body, { version: "1.1" });
const rsd = (op, body) => awsJson("redshift-data", `RedshiftData.${op}`, body, { version: "1.1" });
export const DEFAULT_TARGET = `arn:aws:redshift-serverless:us-east-1:${ACCT}:namespace/vyomi-lite`;

async function sources(kind) {
  if (kind === "dynamodb") {
    const r = await awsJson("dynamodb", "DynamoDB_20120810.ListTables", {}, { version: "1.0" });
    return (r.TableNames || []).map((n) => ({ label: n, value: `arn:aws:dynamodb:us-east-1:${ACCT}:table/${n}` }));
  }
  const r = await awsQuery("rds", "DescribeDBInstances", {});
  return asList(r.DescribeDBInstancesResponse?.DescribeDBInstancesResult?.DBInstances?.DBInstance).map((d) => ({ label: d.DBInstanceIdentifier, value: `arn:aws:rds:us-east-1:${ACCT}:db:${d.DBInstanceIdentifier}` }));
}

export async function listIntegrations() {
  return (await glue("DescribeIntegrations", {})).Integrations || [];
}

export async function runSql(sql, database = "dev") {
  const { Id } = await rsd("ExecuteStatement", { Sql: sql, Database: database, WorkgroupName: "vyomi-lite" });
  const d = await rsd("DescribeStatement", { Id });
  if (d.Status !== "FINISHED") throw new Error(d.Error || "Statement failed");
  if (!d.HasResultSet) return { columns: [], rows: [], affected: d.ResultRows };
  const r = await rsd("GetStatementResult", { Id });
  return { columns: r.ColumnMetadata.map((c) => c.name), rows: r.Records.map((row) => row.map((c) => (c.isNull ? "NULL" : Object.values(c)[0]))) };
}

function CreateModal({ kind, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const src = useAsync(() => sources(kind), [kind]);
  const [name, setName] = useState("");
  const [source, setSource] = useState(null);
  const [target, setTarget] = useState(DEFAULT_TARGET);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      if (kind === "dynamodb") await glue("CreateIntegration", { IntegrationName: name, SourceArn: source.value, TargetArn: target });
      else await awsQuery("rds", "CreateIntegration", { IntegrationName: name, SourceArn: source.value, TargetArn: target });
      notify.success(`Zero-ETL integration "${name}" is active.`);
      setName(""); setSource(null); onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create zero-ETL integration" size="medium"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name || !source || !target} onClick={submit}>Create integration</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">
        {error && <ErrorAlert error={error} header="Couldn't create integration" />}
        <FormField label="Integration name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Integration name" placeholder="my-integration" /></FormField>
        <FormField label={kind === "dynamodb" ? "Source DynamoDB table" : "Source RDS database"} description={kind === "dynamodb" ? "Point-in-time recovery must be enabled on the table." : undefined}>
          <Select selectedOption={source} onChange={({ detail }) => setSource(detail.selectedOption)} options={src.data || []} statusType={src.loading ? "loading" : "finished"}
            placeholder={kind === "dynamodb" ? "Choose a table" : "Choose a database"} ariaLabel="Source" empty="Nothing to integrate yet" />
        </FormField>
        <FormField label="Target (Redshift namespace or lakehouse ARN)" description="Vyomi replicates into its in-process Redshift-lite warehouse.">
          <Input value={target} onChange={({ detail }) => setTarget(detail.value)} ariaLabel="Target ARN" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function QueryEditor({ integrations, reloadKey }) {
  const notify = useNotify();
  const dbs = useAsync(async () => (await rsd("ListDatabases", {})).Databases, [reloadKey]);
  const [db, setDb] = useState("dev");
  const [sql, setSql] = useState("SELECT 1");
  const [res, setRes] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async (q = sql) => {
    setBusy(true); setError(null);
    try { setRes(await runSql(q, db)); dbs.reload(); } catch (e) { setError(e); setRes(null); } finally { setBusy(false); }
  };
  return (
    <Container header={<Header variant="h2" description="Redshift Data API over the replicated data. Replication happens when you query; the SQL dialect is SQLite's." actions={
      <SpaceBetween direction="horizontal" size="xs">
        {integrations.slice(0, 3).map((i) => (
          <Button key={i.IntegrationName} onClick={async () => {
            const dn = i.IntegrationName.replace(/[^A-Za-z0-9_]/g, "_");
            try { await runSql(`CREATE DATABASE ${dn} FROM INTEGRATION '${i.IntegrationName}'`); notify.success(`Database ${dn} created from integration.`); setDb(dn); dbs.reload(); } catch (e) { notify.error(e); }
          }}>Create database from {i.IntegrationName}</Button>))}
      </SpaceBetween>}>Query editor (Redshift-lite)<CapabilityBadge id="dynamodb.account.zero-etl" /></Header>}>
      <SpaceBetween size="s">
        <FormField label="Database"><Select selectedOption={{ label: db, value: db }} onChange={({ detail }) => setDb(detail.selectedOption.value)} options={(dbs.data || ["dev"]).map((d) => ({ label: d, value: d }))} ariaLabel="Database" /></FormField>
        <FormField label="SQL"><Textarea value={sql} rows={4} onChange={({ detail }) => setSql(detail.value)} ariaLabel="SQL statement" /></FormField>
        <Box><Button variant="primary" loading={busy} onClick={() => run()}>Run</Button></Box>
        {error && <ErrorAlert error={error} header="Statement failed" />}
        {res && <Table variant="embedded" items={res.rows.map((r, i) => ({ _i: i, r }))} trackBy="_i" empty={<Box textAlign="center">No rows</Box>}
          columnDefinitions={res.columns.map((c, ci) => ({ id: c, header: c, cell: (it) => String(it.r[ci]) }))} header={<Header counter={`(${res.rows.length})`}>Result</Header>} />}
      </SpaceBetween>
    </Container>
  );
}

export default function ZeroEtlIntegrations({ kind = "dynamodb", openCreate = false }) {
  const notify = useNotify();
  const t = useAsync(() => listIntegrations(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(openCreate);
  const items = (t.data || []).filter((i) => (kind === "dynamodb" ? i.SourceArn.includes(":dynamodb:") : true));
  const cur = sel[0];
  const del = async () => {
    try {
      if (cur.SourceArn.includes(":rds:")) await awsQuery("rds", "DeleteIntegration", { IntegrationName: cur.IntegrationName });
      else await glue("DeleteIntegration", { IntegrationIdentifier: cur.IntegrationName });
      notify.success(`Integration ${cur.IntegrationName} deleted.`); setSel([]); t.reload();
    } catch (e) { notify.error(e); }
  };
  return (
    <ContentLayout header={<Header variant="h1" description="Replicate data from your databases into an analytics warehouse without building ETL pipelines.">{kind === "dynamodb" ? "Integrations" : "Zero-ETL integrations"}</Header>}>
      <SpaceBetween size="l">
        <Table
          header={<Header counter={`(${items.length})`} actions={<SpaceBetween direction="horizontal" size="xs">
            <Button iconName="refresh" ariaLabel="Refresh" onClick={t.reload} />
            <Button disabled={!cur} onClick={del}>Delete</Button>
            <Button variant="primary" onClick={() => setCreate(true)}>Create zero-ETL integration</Button></SpaceBetween>}>Zero-ETL integrations<CapabilityBadge id={kind === "dynamodb" ? "dynamodb.account.zero-etl" : "rds.zero-etl"} /></Header>}
          items={items} loading={t.loading} trackBy="IntegrationName" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
          columnDefinitions={[
            { id: "name", header: "Integration name", cell: (i) => i.IntegrationName, isRowHeader: true },
            { id: "status", header: "Status", cell: (i) => <StatusIndicator type={String(i.Status).toUpperCase() === "ACTIVE" ? "success" : "in-progress"}>{String(i.Status).toUpperCase()}</StatusIndicator> },
            { id: "src", header: "Source", cell: (i) => i.SourceArn },
            { id: "tgt", header: "Target", cell: (i) => i.TargetArn },
          ]}
          empty={<Box textAlign="center"><b>No zero-ETL integrations</b></Box>} />
        {t.error && <ErrorAlert error={t.error} />}
        <QueryEditor integrations={items} reloadKey={items.length} />
      </SpaceBetween>
      <CreateModal kind={kind} visible={create} onDismiss={() => setCreate(false)} onDone={t.reload} />
    </ContentLayout>
  );
}
