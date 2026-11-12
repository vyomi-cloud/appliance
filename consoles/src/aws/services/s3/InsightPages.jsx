/* S3 account pages backed by the shared core (sweep S3-3): Table buckets (S3 Tables), IAM Access Analyzer
 * for S3, Storage Lens dashboards and groups. Capability ids: s3.account.table-buckets / external-access / storage-lens. */
import { useEffect, useMemo, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import LineChart from "@cloudscape-design/components/line-chart";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Multiselect from "@cloudscape-design/components/multiselect";
import Select from "@cloudscape-design/components/select";
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue } from "../../kit/common.jsx";
import * as api from "./api.js";
import * as ins from "./insightApi.js";

const Loading = () => <StatusIndicator type="loading">Loading</StatusIndicator>;
const opt = (v, label = v, extra = {}) => ({ value: v, label, ...extra });
const Empty = ({ title, children }) => <Box textAlign="center" color="inherit"><b>{title}</b><Box variant="p" color="inherit">{children}</Box></Box>;
const Tile = ({ label, value, id, note }) => (
  <div data-testid={id}><Box variant="awsui-key-label">{label}</Box><Box variant="h1" fontWeight="normal">{value}</Box>{note && <Box variant="small" color="text-body-secondary">{note}</Box>}</div>
);
const pctBar = (p) => (
  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
    <div style={{ width: 90, height: 8, background: "#e9ebed", borderRadius: 4 }}><div style={{ width: `${Math.min(100, p)}%`, height: 8, background: "#0972d3", borderRadius: 4 }} /></div>
    <span>{p}%</span>
  </div>
);
const SYSTEM_POLICY = (arn) => JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { AWS: "arn:aws:iam::123456789012:root" }, Action: "s3tables:*", Resource: `${arn}/*` }] }, null, 2);

// ═════════════════════════════════ Table buckets ═════════════════════════════════
export function TableBuckets() {
  const notify = useNotify();
  const list = useAsync(() => ins.listTableBuckets(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [del, setDel] = useState(null);
  const [saving, setSaving] = useState(false);
  const rows = list.data || [];
  const arn = sel[0]?.arn;
  const act = async (fn, ok, after) => { try { await fn(); notify.success(ok); after && after(); } catch (e) { notify.error(e); } };
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="s3.account.table-buckets" title="Table buckets" counter={`(${rows.length})`}
        description="Table buckets are purpose-built for tabular data stored as Apache Iceberg tables."
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={list.reload} />
          <Button ariaLabel="Delete table bucket" disabled={sel.length !== 1} onClick={() => setDel({ name: sel[0].name, typed: "" })}>Delete</Button>
          <Button variant="primary" onClick={() => setCreate({ name: "", sse: "AES256", kms: "" })}>Create table bucket</Button>
        </SpaceBetween>}>
        {list.loading ? <Loading /> : list.error ? <ErrorAlert error={list.error} />
          : <Table variant="embedded" items={rows} trackBy="arn" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
              columnDefinitions={[
                { id: "n", header: "Name", cell: (b) => b.name },
                { id: "r", header: "AWS Region", cell: () => "US East (N. Virginia) us-east-1" },
                { id: "arn", header: "Table bucket ARN", cell: (b) => b.arn },
                { id: "c", header: "Creation date", cell: (b) => fmtDate(b.createdAt) },
              ]}
              empty={<Empty title="No table buckets">Create a table bucket to start storing Iceberg tables.</Empty>} />}
      </CapabilityContainer>
      {arn && <TableBucketDetail key={arn} arn={arn} name={sel[0].name} />}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create table bucket"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} disabled={!create?.name} onClick={async () => {
            setSaving(true);
            try {
              await ins.createTableBucket(create.name, create.sse === "aws:kms" ? { sseAlgorithm: "aws:kms", kmsKeyArn: create.kms } : undefined);
              notify.success(`Successfully created table bucket ${create.name}.${saveNotice("s3.account.table-buckets")}`);
              setCreate(null); list.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create table bucket</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Table bucket name" description="3-63 characters: lowercase letters, numbers and hyphens. Must be unique in this Region."><Input value={create.name} ariaLabel="Table bucket name" onChange={({ detail: d }) => setCreate({ ...create, name: d.value })} /></FormField>
          <FormField label="Encryption type">
            <SegmentedControl selectedId={create.sse} onChange={({ detail: d }) => setCreate({ ...create, sse: d.selectedId })} options={[{ id: "AES256", text: "SSE-S3" }, { id: "aws:kms", text: "SSE-KMS" }]} />
          </FormField>
          {create.sse === "aws:kms" && <FormField label="AWS KMS key ARN"><Input value={create.kms} ariaLabel="KMS key ARN" placeholder="arn:aws:kms:us-east-1:123456789012:key/..." onChange={({ detail: d }) => setCreate({ ...create, kms: d.value })} /></FormField>}
        </SpaceBetween>}
      </Modal>
      <Modal visible={!!del} onDismiss={() => setDel(null)} header="Delete table bucket"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setDel(null)}>Cancel</Button>
          <Button variant="primary" disabled={del?.typed !== del?.name} onClick={() => act(() => ins.deleteTableBucket(sel[0].arn), `Successfully deleted table bucket ${del.name}.`, () => { setDel(null); setSel([]); list.reload(); })}>Delete table bucket</Button>
        </SpaceBetween></Box>}>
        {del && <SpaceBetween size="m">
          <Alert type="warning">A table bucket must be empty (no namespaces or tables) before it can be deleted.</Alert>
          <FormField label={`To confirm deletion, enter the table bucket name (${del.name}).`}><Input value={del.typed} ariaLabel="Confirm table bucket name" onChange={({ detail: d }) => setDel({ ...del, typed: d.value })} /></FormField>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}

function TableBucketDetail({ arn, name }) {
  const notify = useNotify();
  const det = useAsync(() => ins.getTableBucketDetail(arn), [arn]);
  const nss = useAsync(() => ins.listNamespaces(arn), [arn]);
  const tbls = useAsync(() => ins.listTables(arn), [arn]);
  const [selT, setSelT] = useState([]);
  const [selN, setSelN] = useState([]);
  const [newNs, setNewNs] = useState(null);
  const [newTbl, setNewTbl] = useState(null);
  const [policy, setPolicy] = useState("");
  const [maint, setMaint] = useState(null);
  const all = () => { det.reload(); nss.reload(); tbls.reload(); };
  const act = async (fn, ok, after) => { try { await fn(); notify.success(ok); after ? after() : all(); } catch (e) { notify.error(e); } };
  useEffect(() => { setPolicy(det.data?.policy || ""); setMaint(det.data?.maintenance?.icebergUnreferencedFileRemoval || null); }, [det.data]);
  const N = nss.data || [], T = tbls.data || [];
  const d = det.data;
  const parseFields = (txt) => txt.split("\n").map((l) => l.trim()).filter(Boolean).map((l, i) => {
    const [n, t = "string", req] = l.split(/[:,\s]+/);
    return { id: i + 1, name: n, type: t, required: req === "required" };
  });
  const sel = selT[0];
  return (
    <SpaceBetween size="l">
      <Header variant="h1" description={arn}>{name}</Header>
      <Tabs tabs={[
        { id: "tables", label: "Namespaces and tables", content: (
          <SpaceBetween size="l">
            <CapabilityContainer id="s3.account.table-buckets" title="Namespaces" counter={`(${N.length})`}
              actions={<SpaceBetween direction="horizontal" size="xs">
                <Button ariaLabel="Delete namespace" disabled={selN.length !== 1} onClick={() => act(() => ins.deleteNamespace(arn, selN[0].name), `Successfully deleted namespace ${selN[0].name}.`, () => { setSelN([]); all(); })}>Delete</Button>
                <Button variant="primary" onClick={() => setNewNs({ name: "" })}>Create namespace</Button>
              </SpaceBetween>}>
              <Table variant="embedded" items={N} trackBy="name" selectionType="single" selectedItems={selN} onSelectionChange={({ detail }) => setSelN(detail.selectedItems)}
                columnDefinitions={[
                  { id: "n", header: "Namespace", cell: (n) => n.name },
                  { id: "t", header: "Tables", cell: (n) => T.filter((t) => t.namespace === n.name).length },
                  { id: "c", header: "Created", cell: (n) => fmtDate(n.created) },
                ]} empty={<Empty title="No namespaces">Create a namespace to organise tables.</Empty>} />
            </CapabilityContainer>
            <CapabilityContainer id="s3.account.table-buckets" title="Tables" counter={`(${T.length})`}
              actions={<SpaceBetween direction="horizontal" size="xs">
                <Button ariaLabel="Delete table" disabled={selT.length !== 1} onClick={() => act(() => ins.deleteTable(arn, sel.namespace, sel.name), `Successfully deleted table ${sel.name}.`, () => { setSelT([]); all(); })}>Delete</Button>
                <Button variant="primary" disabled={!N.length} onClick={() => setNewTbl({ ns: N[0].name, name: "", fields: "id:long:required\nname:string\ncreated_at:timestamp" })}>Create table</Button>
              </SpaceBetween>}>
              <Table variant="embedded" items={T} trackBy="arn" selectionType="single" selectedItems={selT} onSelectionChange={({ detail }) => setSelT(detail.selectedItems)}
                columnDefinitions={[
                  { id: "n", header: "Name", cell: (t) => t.name },
                  { id: "ns", header: "Namespace", cell: (t) => t.namespace },
                  { id: "ty", header: "Format", cell: () => "Apache Iceberg" },
                  { id: "m", header: "Last modified", cell: (t) => fmtDate(t.modified) },
                  { id: "a", header: "Table ARN", cell: (t) => t.arn },
                ]} empty={<Empty title="No tables">{N.length ? "Create a table in a namespace." : "Create a namespace first."}</Empty>} />
            </CapabilityContainer>
            {sel && <TableDetail key={sel.arn} bucketArn={arn} t={sel} />}
          </SpaceBetween>) },
        { id: "props", label: "Properties", content: det.loading ? <Loading /> : det.error ? <ErrorAlert error={det.error} /> : (
          <SpaceBetween size="l">
            <KeyValue title="Table bucket overview" items={[["Name", d.name], ["Table bucket ARN", d.arn], ["Table bucket ID", d.tableBucketId], ["Owner account", d.ownerAccountId], ["Created", fmtDate(d.createdAt)],
              ["Default encryption", d.encryption?.sseAlgorithm === "aws:kms" ? `SSE-KMS (${d.encryption.kmsKeyArn})` : "SSE-S3 (AES256)"], ["Storage class", d.storageClass || "STANDARD"]]} />
            <CapabilityContainer id="s3.account.table-buckets" title="Maintenance - unreferenced file removal"
              description="Configured and returned; Vyomi never runs the maintenance job." actions={<Button onClick={() => act(() => ins.putTableBucketMaintenance(arn, maint), `Successfully saved the maintenance configuration.${saveNotice("s3.account.table-buckets")}`)}>Save</Button>}>
              {maint && <SpaceBetween size="s">
                <Checkbox checked={maint.status === "enabled"} onChange={({ detail }) => setMaint({ ...maint, status: detail.checked ? "enabled" : "disabled" })}>Enabled</Checkbox>
                <ColumnLayout columns={2}>
                  <FormField label="Unreferenced days"><Input type="number" ariaLabel="Unreferenced days" value={String(maint.settings?.icebergUnreferencedFileRemoval?.unreferencedDays ?? 3)} onChange={({ detail: x }) => setMaint({ ...maint, settings: { icebergUnreferencedFileRemoval: { ...maint.settings?.icebergUnreferencedFileRemoval, unreferencedDays: Math.max(1, Number(x.value) || 1) } } })} /></FormField>
                  <FormField label="Noncurrent days"><Input type="number" ariaLabel="Noncurrent days" value={String(maint.settings?.icebergUnreferencedFileRemoval?.nonCurrentDays ?? 10)} onChange={({ detail: x }) => setMaint({ ...maint, settings: { icebergUnreferencedFileRemoval: { ...maint.settings?.icebergUnreferencedFileRemoval, nonCurrentDays: Math.max(1, Number(x.value) || 1) } } })} /></FormField>
                </ColumnLayout>
              </SpaceBetween>}
            </CapabilityContainer>
          </SpaceBetween>) },
        { id: "perm", label: "Permissions", content: det.loading ? <Loading /> : (
          <CapabilityContainer id="s3.account.table-buckets" title="Table bucket policy" description="Stored and returned; Vyomi does not evaluate it against a caller."
            actions={<SpaceBetween direction="horizontal" size="xs">
              <Button disabled={!d?.policy} onClick={() => act(() => ins.deleteTableBucketPolicy(arn), "Successfully deleted the table bucket policy.")}>Delete</Button>
              <Button variant="primary" disabled={!policy.trim()} onClick={() => act(() => ins.putTableBucketPolicy(arn, policy), `Successfully saved the table bucket policy.${saveNotice("s3.account.table-buckets")}`)}>Save changes</Button>
            </SpaceBetween>}>
            <Textarea value={policy} rows={10} ariaLabel="Table bucket policy" placeholder={SYSTEM_POLICY(arn)} onChange={({ detail: x }) => setPolicy(x.value)} />
          </CapabilityContainer>) },
      ]} />
      <Modal visible={!!newNs} onDismiss={() => setNewNs(null)} header="Create namespace"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setNewNs(null)}>Cancel</Button>
          <Button variant="primary" disabled={!newNs?.name} onClick={() => act(() => ins.createNamespace(arn, newNs.name), `Successfully created namespace ${newNs.name}.`, () => { setNewNs(null); all(); })}>Create namespace</Button>
        </SpaceBetween></Box>}>
        {newNs && <FormField label="Namespace name" description="Lowercase letters, numbers and underscores; must not start with aws."><Input value={newNs.name} ariaLabel="Namespace name" onChange={({ detail: x }) => setNewNs({ name: x.value })} /></FormField>}
      </Modal>
      <Modal visible={!!newTbl} onDismiss={() => setNewTbl(null)} header="Create table" size="large"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setNewTbl(null)}>Cancel</Button>
          <Button variant="primary" disabled={!newTbl?.name} onClick={() => act(() => ins.createTable(arn, newTbl.ns, newTbl.name, parseFields(newTbl.fields)), `Successfully created table ${newTbl.name}.${saveNotice("s3.account.table-buckets")}`, () => { setNewTbl(null); all(); })}>Create table</Button>
        </SpaceBetween></Box>}>
        {newTbl && <SpaceBetween size="m">
          <FormField label="Namespace"><Select selectedOption={opt(newTbl.ns)} options={N.map((n) => opt(n.name))} ariaLabel="Namespace" onChange={({ detail: x }) => setNewTbl({ ...newTbl, ns: x.selectedOption.value })} /></FormField>
          <FormField label="Table name" description="Lowercase letters, numbers and underscores."><Input value={newTbl.name} ariaLabel="Table name" onChange={({ detail: x }) => setNewTbl({ ...newTbl, name: x.value })} /></FormField>
          <FormField label="Schema fields" description="One per line: name:type[:required] (Iceberg types such as long, int, string, double, timestamp, date, boolean). Leave empty for an empty schema.">
            <Textarea value={newTbl.fields} rows={5} ariaLabel="Schema fields" onChange={({ detail: x }) => setNewTbl({ ...newTbl, fields: x.value })} />
          </FormField>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}

function TableDetail({ bucketArn, t }) {
  const notify = useNotify();
  const det = useAsync(() => ins.getTableDetail(bucketArn, t.namespace, t.name), [t.arn]);
  const files = useAsync(async () => (det.data ? ins.listTableFiles(det.data.warehouseLocation) : []), [det.data?.warehouseLocation]);
  const [up, setUp] = useState(null);
  const d = det.data;
  return (
    <CapabilityContainer id="s3.account.table-buckets" title={`Table - ${t.namespace}.${t.name}`}
      actions={<Button iconName="refresh" ariaLabel="Refresh table" onClick={() => { det.reload(); files.reload(); }} />}>
      {det.loading ? <Loading /> : det.error ? <ErrorAlert error={det.error} /> : (
        <SpaceBetween size="m">
          <div data-testid="table-detail"><KeyValue columns={2} items={[
            ["Table ARN", d.tableARN], ["Format", d.format], ["Warehouse location", <span data-testid="table-warehouse">{d.warehouseLocation}</span>],
            ["Metadata location", <span data-testid="table-metadata-location">{d.metadataLocation}</span>], ["Version token", d.versionToken], ["Created", fmtDate(d.createdAt)],
            ["Compaction", d.maintenance?.icebergCompaction?.status], ["Snapshot management", d.maintenance?.icebergSnapshotManagement?.status]]} /></div>
          <Table variant="embedded" header={<Header variant="h3" counter={`(${(files.data || []).length})`} actions={<Button onClick={() => setUp({ key: "data/part-00000.parquet", body: "" })}>Add file</Button>}>Files in the table's warehouse</Header>}
            items={files.data || []} trackBy="key" loading={files.loading}
            columnDefinitions={[{ id: "k", header: "Key", cell: (f) => f.key }, { id: "s", header: "Size", cell: (f) => fmtBytes(f.size) }, { id: "m", header: "Last modified", cell: (f) => fmtDate(f.modified) }]}
            empty={<Empty title="No files">Files written to the warehouse bucket appear here.</Empty>} />
          <Box variant="small" color="text-body-secondary">The warehouse is a real bucket in the object store (hidden from the bucket list); Vyomi does not read Parquet/manifest contents or run Iceberg maintenance.</Box>
        </SpaceBetween>)}
      <Modal visible={!!up} onDismiss={() => setUp(null)} header="Add file to the table warehouse"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setUp(null)}>Cancel</Button>
          <Button variant="primary" disabled={!up?.key} onClick={async () => { try { await ins.uploadTableFile(d.warehouseLocation, up.key, up.body); notify.success(`Added ${up.key}.`); setUp(null); files.reload(); } catch (e) { notify.error(e); } }}>Add file</Button>
        </SpaceBetween></Box>}>
        {up && <SpaceBetween size="m">
          <FormField label="Key (under data/ or metadata/)"><Input value={up.key} ariaLabel="File key" onChange={({ detail: x }) => setUp({ ...up, key: x.value })} /></FormField>
          <FormField label="Contents"><Textarea value={up.body} rows={4} ariaLabel="File contents" onChange={({ detail: x }) => setUp({ ...up, body: x.value })} /></FormField>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

// ═════════════════════════════════ IAM Access Analyzer for S3 ═════════════════════════════════
export function AccessAnalyzer() {
  const notify = useNotify();
  const an = useAsync(() => ins.accessAnalysis(), []);
  const [tab, setTab] = useState("Active");
  const [sel, setSel] = useState([]);
  const [block, setBlock] = useState(null);
  const [filter, setFilter] = useState("");
  const d = an.data;
  const all = d?.findings || [];
  const active = all.filter((f) => f.status === "Active");
  const rows = (tab === "All" ? all : all.filter((f) => f.status === tab)).filter((f) => !filter || f.resource.includes(filter));
  const f = sel[0];
  const publicBuckets = (d?.buckets || []).filter((b) => b.public);
  const act = async (fn, ok) => { try { await fn(); notify.success(ok); setSel([]); an.reload(); } catch (e) { notify.error(e); } };
  const ALL_ON = { BlockPublicAcls: true, IgnorePublicAcls: true, BlockPublicPolicy: true, RestrictPublicBuckets: true };
  const blockAll = async () => {
    try {
      if (block.scope === "account") await ins.putAccountPab(ALL_ON);
      else await api.putPublicAccessBlock(block.bucket, ALL_ON);
      notify.success(block.scope === "account" ? "Successfully enabled Block all public access for this account." : `Successfully enabled Block all public access for ${block.bucket}.`);
      setBlock(null); an.reload();
    } catch (e) { notify.error(e); }
  };
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="s3.account.external-access" title="IAM Access Analyzer for S3"
        description="Findings show which buckets and access points allow public access or access from other AWS accounts and organizations, computed from their current policies, ACLs and Block Public Access settings."
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh findings" onClick={an.reload} />
          <Button variant="primary" onClick={() => setBlock({ scope: "account", bucket: "" })}>Review and block all public access</Button>
        </SpaceBetween>}>
        {an.loading ? <Loading /> : an.error ? <ErrorAlert error={an.error} /> : (
          <SpaceBetween size="l">
            <ColumnLayout columns={4} variant="text-grid">
              <Tile id="aa-public" label="Public" value={active.filter((x) => x.kind === "Public").length} note="active findings" />
              <Tile id="aa-shared" label="Shared with other AWS accounts or organizations" value={active.filter((x) => x.kind === "Shared").length} note="active findings" />
              <Tile id="aa-archived" label="Archived" value={all.filter((x) => x.status === "Archived").length} />
              <Tile id="aa-bpa" label="Account Block Public Access" value={Object.values(d.accountBlockPublicAccess).every(Boolean) ? "All on" : Object.values(d.accountBlockPublicAccess).some(Boolean) ? "Partly on" : "Off"} />
            </ColumnLayout>
            {publicBuckets.length > 0 && <Alert type="warning" header={`${publicBuckets.length} bucket${publicBuckets.length > 1 ? "s are" : " is"} publicly accessible`}
              action={<Button onClick={() => setBlock({ scope: "bucket", bucket: publicBuckets[0].name })}>Block public access</Button>}>
              {publicBuckets.map((b) => b.name).join(", ")}
            </Alert>}
            <Tabs activeTabId={tab} onChange={({ detail }) => { setTab(detail.activeTabId); setSel([]); }} tabs={["Active", "Archived", "All"].map((id) => ({ id, label: id, content: null }))} />
            <Table variant="embedded" items={rows} trackBy="id" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
              filter={<Input value={filter} ariaLabel="Filter findings by resource" placeholder="Filter by bucket or access point name" onChange={({ detail: x }) => setFilter(x.value)} />}
              columnDefinitions={[
                { id: "r", header: "Name", cell: (x) => x.resource },
                { id: "t", header: "Type", cell: (x) => (x.resourceType === "AWS::S3::AccessPoint" ? "Access point" : "Bucket") },
                { id: "a", header: "Access", cell: (x) => <StatusIndicator type={x.kind === "Public" ? "error" : "warning"}>{x.kind === "Public" ? "Public" : "Shared with other accounts / orgs"}</StatusIndicator> },
                { id: "v", header: "Shared through", cell: (x) => x.via },
                { id: "p", header: "Principal", cell: (x) => (x.principal === "*" ? "Anyone (*)" : x.principal) },
                { id: "s", header: "Status", cell: (x) => x.status },
                { id: "u", header: "Updated", cell: (x) => fmtDate(x.updatedAt) },
              ]}
              empty={<Empty title={`No ${tab === "All" ? "" : tab.toLowerCase() + " "}findings`}>No bucket or access point policy, ACL or Block Public Access setting currently grants public or cross-account access.</Empty>} />
            <Box variant="small" color="text-body-secondary">{d.analyzer.note} {d.buckets.length} bucket(s) analysed.</Box>
          </SpaceBetween>)}
      </CapabilityContainer>
      {f && (
        <CapabilityContainer id="s3.account.external-access" title={`Finding - ${f.resource}`}
          actions={<SpaceBetween direction="horizontal" size="xs">
            {f.status === "Active"
              ? <Button onClick={() => act(() => ins.archiveFinding(f.id), `Archived the finding for ${f.resource}.`)}>Archive</Button>
              : <Button onClick={() => act(() => ins.unarchiveFinding(f.id), `Unarchived the finding for ${f.resource}.`)}>Unarchive</Button>}
            <Button disabled={f.resourceType !== "AWS::S3::Bucket" && !f.bucket} onClick={() => setBlock({ scope: "bucket", bucket: f.bucket || f.resource })}>Block public access</Button>
            {f.resourceType === "AWS::S3::Bucket" && <Button href={`#/s3/buckets/${f.resource}`} iconName="external" iconAlign="right">Open bucket</Button>}
          </SpaceBetween>}>
          <div data-testid="finding-detail"><SpaceBetween size="m">
            <KeyValue columns={3} items={[["Resource ARN", f.resourceArn], ["Access", f.access], ["Shared through", f.via], ["Principal", f.principal === "*" ? "Anyone (*)" : f.principal], ["Status", f.status], ["First found", fmtDate(f.firstSeen)]]} />
            <Box variant="h4">Why this is reported</Box>
            <ul style={{ margin: 0, paddingLeft: 18 }}>{f.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            <Box variant="h4">Permissions granted</Box>
            <div>{f.actions.join(", ")}</div>
          </SpaceBetween></div>
        </CapabilityContainer>
      )}
      <Modal visible={!!block} onDismiss={() => setBlock(null)} header="Block all public access"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setBlock(null)}>Cancel</Button><Button variant="primary" onClick={blockAll}>Block all public access</Button></SpaceBetween></Box>}>
        {block && <SpaceBetween size="m">
          <FormField label="Apply to">
            <SegmentedControl selectedId={block.scope} onChange={({ detail: x }) => setBlock({ ...block, scope: x.selectedId, bucket: block.bucket || publicBuckets[0]?.name || d?.buckets?.[0]?.name || "" })}
              options={[{ id: "account", text: "All buckets in this account" }, { id: "bucket", text: "One bucket" }]} />
          </FormField>
          {block.scope === "bucket" && <FormField label="Bucket"><Select selectedOption={block.bucket ? opt(block.bucket) : null} options={(d?.buckets || []).map((b) => opt(b.name))} ariaLabel="Bucket" onChange={({ detail: x }) => setBlock({ ...block, bucket: x.selectedOption.value })} /></FormField>}
          <Box>Turns on BlockPublicAcls, IgnorePublicAcls, BlockPublicPolicy and RestrictPublicBuckets. Public policy statements and public ACL grants stop producing findings; cross-account shares remain and must be removed from the policy or ACL.</Box>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}

/** The compact summary on the buckets list page. */
export function ExternalAccessSummary() {
  const an = useAsync(() => ins.accessAnalysis(), []);
  const active = (an.data?.findings || []).filter((f) => f.status === "Active");
  return (
    <CapabilityContainer id="s3.account.external-access" title="External access summary"
      description="Public and cross-account access to your buckets and access points, from IAM Access Analyzer for S3."
      actions={<Button href="#/s3/access-analyzer">View all findings</Button>}>
      {an.loading ? <Loading /> : an.error ? <ErrorAlert error={an.error} /> : (
        <ColumnLayout columns={3} variant="text-grid">
          <Tile id="ext-public" label="Public" value={active.filter((f) => f.kind === "Public").length} note="findings" />
          <Tile id="ext-shared" label="Shared with other accounts / orgs" value={active.filter((f) => f.kind === "Shared").length} note="findings" />
          <Tile id="ext-clean" label="Buckets with no external access" value={(an.data.buckets || []).filter((b) => !b.activeFindings).length} note={`of ${an.data.buckets.length}`} />
        </ColumnLayout>)}
    </CapabilityContainer>
  );
}

// ═════════════════════════════════ Storage Lens dashboards ═════════════════════════════════
export function StorageLensDashboards() {
  const notify = useNotify();
  const list = useAsync(() => ins.listLensConfigs(), []);
  const [sel, setSel] = useState([]);
  const [view, setView] = useState("");
  const [pick, setPick] = useState("");
  const [edit, setEdit] = useState(null);
  const [del, setDel] = useState(false);
  const rows = list.data || [];
  useEffect(() => {          // after create/save, select (and show) the saved dashboard once the list has reloaded
    const r = pick && (list.data || []).find((x) => x.id === pick);
    if (r) { setSel([r]); setView(r.id); setPick(""); }
  }, [list.data, pick]);
  const buckets = useAsync(() => api.listBuckets(), []);
  const groups = useAsync(() => ins.listLensGroups(), []);
  const act = async (fn, ok, after) => { try { await fn(); notify.success(ok); after && after(); } catch (e) { notify.error(e); } };
  const openEdit = async (id) => {
    if (!id) { setEdit({ isNew: true, id: "", enabled: true, include: [], exclude: [], prefixEnabled: true, delimiter: "/", maxDepth: 3, minPct: 1, groups: [], tags: [] }); return; }
    try { const c = await ins.getLensConfig(id); setEdit({ ...c, tags: await ins.getLensTags(id) }); } catch (e) { notify.error(e); }
  };
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="s3.account.storage-lens" title="Dashboards" counter={`(${rows.length})`}
        description="Storage Lens gives organization-wide visibility into object storage usage, computed here from the objects in this environment."
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={list.reload} />
          <Button ariaLabel="Edit dashboard" disabled={sel.length !== 1} onClick={() => openEdit(sel[0].id)}>Edit</Button>
          <Button ariaLabel="Delete dashboard" disabled={sel.length !== 1 || sel[0]?.id === ins.DEFAULT_DASHBOARD} onClick={() => setDel(true)}>Delete</Button>
          <Button variant="primary" onClick={() => openEdit("")}>Create dashboard</Button>
        </SpaceBetween>}>
        {list.loading ? <Loading /> : list.error ? <ErrorAlert error={list.error} /> : (
          <Table variant="embedded" items={rows} trackBy="id" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => { setSel(detail.selectedItems); setView(detail.selectedItems[0]?.id || ""); }}
            columnDefinitions={[
              { id: "n", header: "Dashboard name", cell: (c) => <Link onFollow={() => { setSel([c]); setView(c.id); }}>{c.id}</Link> },
              { id: "t", header: "Type", cell: (c) => (c.id === ins.DEFAULT_DASHBOARD ? "Default (account)" : "Custom") },
              { id: "r", header: "Home Region", cell: (c) => c.region },
              { id: "s", header: "Status", cell: (c) => <StatusIndicator type={c.enabled ? "success" : "stopped"}>{c.enabled ? "Enabled" : "Disabled"}</StatusIndicator> },
              { id: "a", header: "ARN", cell: (c) => c.arn },
            ]} empty={<Empty title="No dashboards">Create a dashboard.</Empty>} />)}
      </CapabilityContainer>
      {view && <LensDashboard key={view} id={view} groupsList={groups.data || []} />}
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header={edit?.isNew ? "Create dashboard" : `Edit dashboard ${edit?.id}`} size="large"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" disabled={!edit?.id} onClick={() => act(() => ins.putLensConfig(edit), `Successfully ${edit.isNew ? "created" : "saved"} dashboard ${edit.id}.${saveNotice("s3.account.storage-lens")}`, () => { const id = edit.id; setEdit(null); setPick(id); list.reload(); })}>{edit?.isNew ? "Create dashboard" : "Save changes"}</Button>
        </SpaceBetween></Box>}>
        {edit && <SpaceBetween size="m">
          <FormField label="Dashboard name" description="Letters, numbers, hyphens, underscores and periods (1-64)."><Input value={edit.id} disabled={!edit.isNew} ariaLabel="Dashboard name" onChange={({ detail: x }) => setEdit({ ...edit, id: x.value })} /></FormField>
          <Checkbox checked={edit.enabled} onChange={({ detail: x }) => setEdit({ ...edit, enabled: x.checked })}>Enable dashboard</Checkbox>
          <FormField label="Buckets to include" description="Leave empty to include every general purpose bucket.">
            <Multiselect selectedOptions={edit.include.map((b) => opt(b))} options={(buckets.data || []).map((b) => opt(b.name))} placeholder="All buckets" ariaLabel="Buckets to include" empty="No buckets"
              onChange={({ detail: x }) => setEdit({ ...edit, include: x.selectedOptions.map((o) => o.value) })} />
          </FormField>
          <Checkbox checked={edit.prefixEnabled} onChange={({ detail: x }) => setEdit({ ...edit, prefixEnabled: x.checked })} description="Aggregate storage by prefix (top prefixes by size).">Prefix aggregation</Checkbox>
          {edit.prefixEnabled && <ColumnLayout columns={3}>
            <FormField label="Delimiter"><Input value={edit.delimiter} ariaLabel="Prefix delimiter" onChange={({ detail: x }) => setEdit({ ...edit, delimiter: x.value.slice(0, 1) })} /></FormField>
            <FormField label="Maximum prefix depth (1-10)"><Input type="number" value={String(edit.maxDepth)} ariaLabel="Maximum prefix depth" onChange={({ detail: x }) => setEdit({ ...edit, maxDepth: Number(x.value) })} /></FormField>
            <FormField label="Minimum prefix size (% of storage)"><Input type="number" value={String(edit.minPct)} ariaLabel="Minimum prefix size percentage" onChange={({ detail: x }) => setEdit({ ...edit, minPct: Number(x.value) })} /></FormField>
          </ColumnLayout>}
          <FormField label="Storage Lens groups" description="Group aggregation: bytes and objects matching each group's filter.">
            <Multiselect selectedOptions={edit.groups.map((g) => opt(g))} options={(groups.data || []).map((g) => opt(g.name))} placeholder="No groups" ariaLabel="Storage Lens groups" empty="No groups yet"
              onChange={({ detail: x }) => setEdit({ ...edit, groups: x.selectedOptions.map((o) => o.value) })} />
          </FormField>
          <FormField label="Tags (one key=value per line)"><Textarea rows={2} ariaLabel="Dashboard tags" value={edit.tags.map((t) => `${t.key}=${t.value}`).join("\n")}
            onChange={({ detail: x }) => setEdit({ ...edit, tags: x.value.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [k, ...v] = l.split("="); return { key: k, value: v.join("=") }; }) })} /></FormField>
        </SpaceBetween>}
      </Modal>
      <Modal visible={del} onDismiss={() => setDel(false)} header="Delete dashboard"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setDel(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => act(() => ins.deleteLensConfig(sel[0].id), `Successfully deleted dashboard ${sel[0].id}.`, () => { setDel(false); setSel([]); setView(""); list.reload(); })}>Delete dashboard</Button></SpaceBetween></Box>}>
        Delete dashboard <b>{sel[0]?.id}</b>? Its recorded snapshots are removed too.
      </Modal>
    </SpaceBetween>
  );
}

function LensDashboard({ id, groupsList }) {
  const [group, setGroup] = useState("");
  const data = useAsync(() => ins.lensData(id, { group }), [id, group]);
  const d = data.data;
  const s = d?.summary;
  const trend = useMemo(() => (d?.trend || []).map((r) => ({ x: new Date(`${r.date}T00:00:00Z`), y: r.totalBytes })), [d]);
  return (
    <CapabilityContainer id="s3.account.storage-lens" title={`Dashboard - ${id}`}
      description={d ? `Computed from the object store at ${fmtDate(d.generatedAt)}${d.scope.group ? ` - filtered by group ${d.scope.group}` : ""}.` : undefined}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Select selectedOption={group ? opt(group) : opt("", "No group filter")} ariaLabel="Filter by Storage Lens group" options={[opt("", "No group filter"), ...groupsList.map((g) => opt(g.name))]} onChange={({ detail: x }) => setGroup(x.selectedOption.value)} />
        <Button iconName="refresh" ariaLabel="Refresh dashboard" onClick={data.reload} />
      </SpaceBetween>}>
      {data.loading && !d ? <Loading /> : data.error ? <ErrorAlert error={data.error} /> : (
        <div data-testid="lens-dashboard"><SpaceBetween size="l">
          {!d.enabled && <Alert type="info">This dashboard is disabled. Data is still computed on demand.</Alert>}
          <ColumnLayout columns={4} variant="text-grid">
            <Tile id="lens-total" label="Total storage" value={fmtBytes(s.totalBytes)} note={`${s.totalBytes} bytes`} />
            <Tile id="lens-objects" label="Object count" value={s.objectCount} note={`${s.bucketCount} bucket(s)`} />
            <Tile id="lens-avg" label="Avg. object size" value={fmtBytes(s.avgObjectBytes)} />
            <Tile id="lens-current" label="% current version bytes" value={`${s.currentVersionPct}%`} />
            <Tile id="lens-noncurrent" label="Noncurrent version storage" value={fmtBytes(s.noncurrentBytes)} note={`${s.noncurrentObjects} object version(s)`} />
            <Tile id="lens-markers" label="Delete marker objects" value={s.deleteMarkers} note={`${s.deleteMarkerPct}% of all versions`} />
            <Tile id="lens-mpu" label="Incomplete multipart upload storage" value={fmtBytes(s.incompleteMpuBytes)} note={`${s.incompleteMpuUploads} upload(s), ${s.incompleteMpuPct}%`} />
            <Tile id="lens-versions" label="Noncurrent % of version bytes" value={`${s.noncurrentVersionPct}%`} />
          </ColumnLayout>
          <Box variant="h3">Storage trend (daily snapshots, last 30)</Box>
          <div data-testid="lens-trend">
            <LineChart series={[{ title: "Total storage (bytes)", type: "line", data: trend, valueFormatter: (v) => fmtBytes(v) }]} xScaleType="time" xTitle="Snapshot date" yTitle="Bytes" hideFilter
              ariaLabel="Total storage trend" empty={<Box>No snapshots yet</Box>} noMatch={<Box>No data</Box>} height={180} />
            <Box variant="small" color="text-body-secondary">{d.trend.length} snapshot(s); one is recorded the first time the dashboard is read each day.</Box>
          </div>
          <Tabs tabs={[
            { id: "bucket", label: "By bucket", content: <Table variant="embedded" items={d.byBucket} trackBy="bucket" columnDefinitions={[
              { id: "b", header: "Bucket", cell: (r) => r.bucket }, { id: "rg", header: "Region", cell: (r) => r.region }, { id: "s", header: "Storage", cell: (r) => fmtBytes(r.bytes) },
              { id: "o", header: "Object versions", cell: (r) => r.objects }, { id: "dm", header: "Delete markers", cell: (r) => r.deleteMarkers }, { id: "m", header: "Incomplete MPU", cell: (r) => fmtBytes(r.incompleteMpuBytes) }, { id: "p", header: "% of total", cell: (r) => pctBar(r.pct) }]}
              empty={<Empty title="No buckets">Nothing in scope.</Empty>} /> },
            { id: "class", label: "By storage class", content: <Table variant="embedded" items={d.byStorageClass} trackBy="storageClass" columnDefinitions={[
              { id: "c", header: "Storage class", cell: (r) => r.storageClass }, { id: "s", header: "Storage", cell: (r) => fmtBytes(r.bytes) }, { id: "o", header: "Object versions", cell: (r) => r.objects }, { id: "p", header: "% of total", cell: (r) => pctBar(r.pct) }]}
              empty={<Empty title="No objects">Nothing stored.</Empty>} /> },
            { id: "prefix", label: "By prefix", content: <SpaceBetween size="s">
              {!d.scope.prefixAggregationConfigured && <Box variant="small" color="text-body-secondary">Prefix aggregation is not enabled in this dashboard's configuration; showing the top prefixes with default settings.</Box>}
              <Table variant="embedded" items={d.byPrefix} trackBy={(r) => `${r.bucket}/${r.prefix}`} columnDefinitions={[
                { id: "b", header: "Bucket", cell: (r) => r.bucket }, { id: "p", header: "Prefix", cell: (r) => r.prefix }, { id: "d", header: "Depth", cell: (r) => r.depth },
                { id: "s", header: "Storage (current versions)", cell: (r) => fmtBytes(r.bytes) }, { id: "o", header: "Objects", cell: (r) => r.objects }, { id: "pc", header: "% of total", cell: (r) => pctBar(r.pct) }]}
                empty={<Empty title="No prefixes">Objects with a '{d.scope.prefixDelimiter}' in their key are rolled up by prefix (min {d.scope.minStorageBytesPercentage}% of storage).</Empty>} /></SpaceBetween> },
            { id: "group", label: "By Storage Lens group", content: <Table variant="embedded" items={d.byGroup} trackBy="group" columnDefinitions={[
              { id: "g", header: "Storage Lens group", cell: (r) => r.group }, { id: "s", header: "Storage", cell: (r) => fmtBytes(r.bytes) }, { id: "o", header: "Objects", cell: (r) => r.objects }, { id: "p", header: "% of total", cell: (r) => pctBar(r.pct) }]}
              empty={<Empty title="No groups selected">Edit the dashboard and choose Storage Lens groups to aggregate by.</Empty>} /> },
            { id: "activity", label: "Activity", content: <Alert type="info" header="Activity metrics are not modelled"><span data-testid="lens-activity">{d.activityMetrics.reason}</span></Alert> },
          ]} />
        </SpaceBetween></div>)}
    </CapabilityContainer>
  );
}

// ═════════════════════════════════ Storage Lens groups ═════════════════════════════════
const EMPTY_FILTER = { op: "And", prefixes: [], suffixes: [], tags: [], ageGt: "", ageLt: "", sizeGt: "", sizeLt: "" };
const csv = (v) => v.split(",").map((x) => x.trim()).filter(Boolean);

export function StorageLensGroups() {
  const notify = useNotify();
  const list = useAsync(() => ins.listLensGroups(), []);
  const [sel, setSel] = useState([]);
  const [edit, setEdit] = useState(null);
  const [del, setDel] = useState(false);
  const rows = list.data || [];
  const g = sel[0];
  const detail = useAsync(async () => (g ? ins.getLensGroup(g.name) : null), [g?.name]);
  const act = async (fn, ok, after) => { try { await fn(); notify.success(ok); after && after(); } catch (e) { notify.error(e); } };
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="s3.account.storage-lens" title="Storage Lens groups" counter={`(${rows.length})`}
        description="Storage Lens groups aggregate usage by object prefix, suffix, tag, age and size."
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={list.reload} />
          <Button ariaLabel="Edit group" disabled={!g || !detail.data} onClick={() => setEdit({ isNew: false, name: g.name, filter: detail.data.filter })}>Edit</Button>
          <Button ariaLabel="Delete group" disabled={!g} onClick={() => setDel(true)}>Delete</Button>
          <Button variant="primary" onClick={() => setEdit({ isNew: true, name: "", filter: { ...EMPTY_FILTER } })}>Create Storage Lens group</Button>
        </SpaceBetween>}>
        {list.loading ? <Loading /> : list.error ? <ErrorAlert error={list.error} /> : (
          <Table variant="embedded" items={rows} trackBy="name" selectionType="single" selectedItems={sel} onSelectionChange={({ detail: x }) => setSel(x.selectedItems)}
            columnDefinitions={[{ id: "n", header: "Name", cell: (r) => r.name }, { id: "r", header: "Home Region", cell: (r) => r.region }, { id: "a", header: "ARN", cell: (r) => r.arn }]}
            empty={<Empty title="No Storage Lens groups">Create a group to aggregate usage by a filter.</Empty>} />)}
      </CapabilityContainer>
      {g && (
        <CapabilityContainer id="s3.account.storage-lens" title={`Group - ${g.name}`}>
          {detail.loading || !detail.data ? (detail.error ? <ErrorAlert error={detail.error} /> : <Loading />) : (
            <div data-testid="group-detail"><KeyValue columns={2} items={[["ARN", detail.data.arn], ["Filter", ins.describeFilter(detail.data.filter) || "(none)"]]} /></div>)}
        </CapabilityContainer>
      )}
      <GroupModal edit={edit} setEdit={setEdit} onSave={() => act(
        () => (edit.isNew ? ins.createLensGroup(edit.name, edit.filter) : ins.updateLensGroup(edit.name, edit.filter)),
        `Successfully ${edit.isNew ? "created" : "updated"} Storage Lens group ${edit.name}.`, () => { setEdit(null); list.reload(); detail.reload(); })} />
      <Modal visible={del} onDismiss={() => setDel(false)} header="Delete Storage Lens group"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setDel(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => act(() => ins.deleteLensGroup(g.name), `Successfully deleted Storage Lens group ${g.name}.`, () => { setDel(false); setSel([]); list.reload(); })}>Delete group</Button></SpaceBetween></Box>}>
        Delete Storage Lens group <b>{g?.name}</b>?
      </Modal>
    </SpaceBetween>
  );
}

function GroupModal({ edit, setEdit, onSave }) {
  if (!edit) return <Modal visible={false} />;
  const f = edit.filter;
  const set = (patch) => setEdit({ ...edit, filter: { ...f, ...patch } });
  const fields = [f.prefixes.length, f.suffixes.length, f.tags.length, f.ageGt !== "" || f.ageLt !== "" ? 1 : 0, f.sizeGt !== "" || f.sizeLt !== "" ? 1 : 0].filter(Boolean).length;
  return (
    <Modal visible onDismiss={() => setEdit(null)} header={edit.isNew ? "Create Storage Lens group" : `Edit ${edit.name}`} size="large"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
        <Button variant="primary" disabled={!edit.name || fields === 0} onClick={onSave}>{edit.isNew ? "Create Storage Lens group" : "Save changes"}</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">
        <FormField label="Storage Lens group name" description="Letters, numbers, hyphens and underscores (1-64)."><Input value={edit.name} disabled={!edit.isNew} ariaLabel="Group name" onChange={({ detail: x }) => setEdit({ ...edit, name: x.value })} /></FormField>
        {fields > 1 && <FormField label="Combine filters with"><SegmentedControl selectedId={f.op === "Or" ? "Or" : "And"} onChange={({ detail: x }) => set({ op: x.selectedId })} options={[{ id: "And", text: "AND (all must match)" }, { id: "Or", text: "OR (any may match)" }]} /></FormField>}
        <ColumnLayout columns={2}>
          <FormField label="Prefixes (comma separated)"><Input value={f.prefixes.join(",")} ariaLabel="Prefixes" onChange={({ detail: x }) => set({ prefixes: csv(x.value) })} /></FormField>
          <FormField label="Suffixes (comma separated)"><Input value={f.suffixes.join(",")} ariaLabel="Suffixes" onChange={({ detail: x }) => set({ suffixes: csv(x.value) })} /></FormField>
          <FormField label="Object tags (key=value, comma separated; any may match)"><Input value={f.tags.map((t) => `${t.key}=${t.value}`).join(",")} ariaLabel="Object tags"
            onChange={({ detail: x }) => set({ tags: csv(x.value).map((p) => { const [k, ...v] = p.split("="); return { key: k, value: v.join("=") }; }) })} /></FormField>
          <span />
          <FormField label="Age greater than (days)"><Input type="number" value={String(f.ageGt)} ariaLabel="Age greater than" onChange={({ detail: x }) => set({ ageGt: x.value })} /></FormField>
          <FormField label="Age less than (days)"><Input type="number" value={String(f.ageLt)} ariaLabel="Age less than" onChange={({ detail: x }) => set({ ageLt: x.value })} /></FormField>
          <FormField label="Size greater than (bytes)"><Input type="number" value={String(f.sizeGt)} ariaLabel="Size greater than" onChange={({ detail: x }) => set({ sizeGt: x.value })} /></FormField>
          <FormField label="Size less than (bytes)"><Input type="number" value={String(f.sizeLt)} ariaLabel="Size less than" onChange={({ detail: x }) => set({ sizeLt: x.value })} /></FormField>
        </ColumnLayout>
        <Box variant="small" color="text-body-secondary">Specify at least one filter. Objects are matched on their current version.</Box>
      </SpaceBetween>
    </Modal>
  );
}
