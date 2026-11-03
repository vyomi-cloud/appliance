/* S3 Vector buckets (service s3vectors): buckets -> indexes -> vectors + exact similarity query.
 * Capability id: s3.account.vector-buckets. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import * as v from "./vectorApi.js";

const CAP = "s3.account.vector-buckets";
const Loading = () => <StatusIndicator type="loading">Loading</StatusIndicator>;
const Empty = ({ title, children }) => <Box textAlign="center" color="inherit"><b>{title}</b><Box variant="p" color="inherit">{children}</Box></Box>;
const when = (t) => (t ? new Date(t * 1000).toLocaleString() : "-");
const parseVec = (s) => String(s).split(/[\s,\[\]]+/).filter(Boolean).map(Number);
const short = (a, n = 6) => (a.length > n ? `[${a.slice(0, n).map((x) => +x.toFixed(4)).join(", ")}, … ${a.length}]` : `[${a.join(", ")}]`);

// ───────────────────────────── Vectors tab ─────────────────────────────
function VectorsTab({ bucket, index, dim }) {
  const notify = useNotify();
  const list = useAsync(() => v.listVectors(bucket, index.indexName), [bucket, index.indexName]);
  const [sel, setSel] = useState([]);
  const [add, setAdd] = useState(null);
  const [saving, setSaving] = useState(false);
  const rows = list.data?.vectors || [];
  return (
    <SpaceBetween size="s">
      <Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button iconName="refresh" ariaLabel="Refresh vectors" onClick={list.reload} />
        <Button disabled={!sel.length} onClick={async () => {
          try { await v.deleteVectors(bucket, index.indexName, sel.map((r) => r.key)); notify.success(`Successfully deleted ${sel.length} vector(s).`); setSel([]); list.reload(); } catch (e) { notify.error(e); }
        }}>Delete</Button>
        <Button variant="primary" onClick={() => setAdd({ key: "", data: "", meta: "" })}>Add vector</Button>
      </SpaceBetween></Box>
      {list.loading ? <Loading /> : list.error ? <ErrorAlert error={list.error} />
        : <Table variant="embedded" items={rows} trackBy="key" selectionType="multi" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
            columnDefinitions={[
              { id: "k", header: "Vector key", cell: (r) => r.key },
              { id: "d", header: `Data (float32 × ${dim})`, cell: (r) => short(r.data?.float32 || []) },
              { id: "m", header: "Metadata", cell: (r) => (r.metadata ? JSON.stringify(r.metadata) : "-") },
            ]}
            empty={<Empty title="No vectors">Add vectors to this index to search them by similarity.</Empty>} />}
      {list.data?.nextToken && <Box color="text-status-inactive">Showing the first 100 vectors.</Box>}
      <Modal visible={!!add} onDismiss={() => setAdd(null)} header="Add vector"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAdd(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} disabled={!add?.key || !add?.data} onClick={async () => {
            setSaving(true);
            try {
              const vec = { key: add.key, data: { float32: parseVec(add.data) } };
              if (add.meta.trim()) vec.metadata = JSON.parse(add.meta);
              await v.putVectors(bucket, index.indexName, [vec]);
              notify.success(`Successfully added vector ${add.key}.${saveNotice(CAP)}`); setAdd(null); list.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Add vector</Button>
        </SpaceBetween></Box>}>
        {add && <SpaceBetween size="m">
          <FormField label="Vector key" description="1-1024 characters. Adding an existing key replaces that vector."><Input value={add.key} ariaLabel="Vector key" onChange={({ detail: d }) => setAdd({ ...add, key: d.value })} /></FormField>
          <FormField label={`Vector data (${dim} numbers)`} description="Comma- or space-separated float32 values."><Textarea value={add.data} ariaLabel="Vector data" rows={3} onChange={({ detail: d }) => setAdd({ ...add, data: d.value })} /></FormField>
          <FormField label="Metadata (optional JSON object)"><Textarea value={add.meta} ariaLabel="Vector metadata" rows={3} placeholder='{"genre": "scifi", "year": 1999}' onChange={({ detail: d }) => setAdd({ ...add, meta: d.value })} /></FormField>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}

// ───────────────────────────── Query tab ─────────────────────────────
function QueryTab({ bucket, index, dim, metric }) {
  const notify = useNotify();
  const [q, setQ] = useState({ vector: "", topK: "5", filter: "" });
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  return (
    <SpaceBetween size="m">
      <FormField label={`Query vector (${dim} numbers)`}><Textarea value={q.vector} ariaLabel="Query vector" rows={2} onChange={({ detail: d }) => setQ({ ...q, vector: d.value })} /></FormField>
      <SpaceBetween direction="horizontal" size="m">
        <FormField label="Top K" description="1-100"><Input value={q.topK} ariaLabel="Top K" inputMode="numeric" onChange={({ detail: d }) => setQ({ ...q, topK: d.value })} /></FormField>
        <FormField label="Metadata filter (optional JSON)" description="$eq $ne $gt $gte $lt $lte $in $nin $exists $and $or"><Input value={q.filter} ariaLabel="Metadata filter" placeholder='{"genre": "scifi"}' onChange={({ detail: d }) => setQ({ ...q, filter: d.value })} /></FormField>
      </SpaceBetween>
      <Button variant="primary" loading={busy} disabled={!q.vector.trim()} onClick={async () => {
        setBusy(true);
        try { setRes(await v.queryVectors(bucket, index.indexName, { vector: parseVec(q.vector), topK: q.topK, filter: q.filter.trim() ? JSON.parse(q.filter) : undefined })); }
        catch (e) { setRes(null); notify.error(e); } finally { setBusy(false); }
      }}>Query</Button>
      {res && <Table variant="embedded" items={res.vectors || []} trackBy="key"
        header={<Box variant="awsui-key-label">Nearest vectors by {metric} distance (exact scan)</Box>}
        columnDefinitions={[
          { id: "k", header: "Vector key", cell: (r) => r.key },
          { id: "d", header: "Distance", cell: (r) => (+r.distance).toFixed(6) },
          { id: "m", header: "Metadata", cell: (r) => (r.metadata ? JSON.stringify(r.metadata) : "-") },
        ]}
        empty={<Empty title="No matches">No vector satisfies the filter.</Empty>} />}
    </SpaceBetween>
  );
}

// ───────────────────────────── Index detail ─────────────────────────────
function IndexDetail({ bucket, name }) {
  const info = useAsync(() => v.getIndex(bucket, name), [bucket, name]);
  if (info.loading) return <Loading />;
  if (info.error) return <ErrorAlert error={info.error} />;
  const i = info.data;
  return (
    <SpaceBetween size="m">
      <KeyValue columns={3} items={[
        ["Index ARN", i.indexArn], ["Dimension", i.dimension], ["Distance metric", i.distanceMetric],
        ["Data type", i.dataType], ["Non-filterable metadata keys", (i.metadataConfiguration?.nonFilterableMetadataKeys || []).join(", ")],
      ]} />
      <Tabs tabs={[
        { id: "vectors", label: "Vectors", content: <VectorsTab bucket={bucket} index={i} dim={i.dimension} /> },
        { id: "query", label: "Query", content: <QueryTab bucket={bucket} index={i} dim={i.dimension} metric={i.distanceMetric} /> },
      ]} />
    </SpaceBetween>
  );
}

// ───────────────────────────── Vector bucket detail (indexes + policy) ─────────────────────────────
function BucketDetail({ name }) {
  const notify = useNotify();
  const idx = useAsync(() => v.listIndexes(name), [name]);
  const pol = useAsync(() => v.getVectorBucketPolicy(name), [name]);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [polEdit, setPolEdit] = useState(null);
  const [saving, setSaving] = useState(false);
  const rows = idx.data || [];
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id={CAP} title={`Vector indexes in ${name}`} counter={`(${rows.length})`}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh indexes" onClick={idx.reload} />
          <Button disabled={sel.length !== 1} onClick={async () => {
            try { await v.deleteIndex(name, sel[0].indexName); notify.success(`Successfully deleted index ${sel[0].indexName}.`); setSel([]); idx.reload(); } catch (e) { notify.error(e); }
          }}>Delete</Button>
          <Button variant="primary" onClick={() => setCreate({ name: "", dimension: "", metric: "cosine", nonFilterable: "" })}>Create vector index</Button>
        </SpaceBetween>}>
        {idx.loading ? <Loading /> : idx.error ? <ErrorAlert error={idx.error} />
          : <Table variant="embedded" items={rows} trackBy="indexName" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
              columnDefinitions={[
                { id: "n", header: "Index name", cell: (r) => r.indexName },
                { id: "a", header: "Index ARN", cell: (r) => r.indexArn },
                { id: "c", header: "Creation date", cell: (r) => when(r.creationTime) },
              ]}
              empty={<Empty title="No vector indexes">Create an index to store and search vectors.</Empty>} />}
      </CapabilityContainer>
      {sel[0] && <CapabilityContainer id={CAP} title={`Index ${sel[0].indexName}`}><IndexDetail key={sel[0].indexName} bucket={name} name={sel[0].indexName} /></CapabilityContainer>}
      <CapabilityContainer id={CAP} title="Vector bucket policy"
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!pol.data} onClick={async () => { try { await v.deleteVectorBucketPolicy(name); notify.success("Successfully deleted the bucket policy."); pol.reload(); } catch (e) { notify.error(e); } }}>Delete</Button>
          <Button onClick={() => setPolEdit({ text: pol.data || "" })}>Edit</Button>
        </SpaceBetween>}>
        {pol.loading ? <Loading /> : pol.error ? <ErrorAlert error={pol.error} /> : pol.data ? <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{pol.data}</pre> : <Box color="text-status-inactive">No bucket policy.</Box>}
      </CapabilityContainer>
      <Modal visible={!!polEdit} onDismiss={() => setPolEdit(null)} header="Edit vector bucket policy"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setPolEdit(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { try { await v.putVectorBucketPolicy(name, polEdit.text); notify.success("Successfully edited the bucket policy."); setPolEdit(null); pol.reload(); } catch (e) { notify.error(e); } }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {polEdit && <FormField label="Policy (JSON)" description="Stored and returned; Vyomi does not evaluate it against callers."><Textarea value={polEdit.text} ariaLabel="Bucket policy" rows={10} onChange={({ detail: d }) => setPolEdit({ text: d.value })} /></FormField>}
      </Modal>
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create vector index"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} disabled={!create?.name || !create?.dimension} onClick={async () => {
            setSaving(true);
            try {
              await v.createIndex(name, { name: create.name, dimension: create.dimension, metric: create.metric, nonFilterable: create.nonFilterable.split(",").map((s) => s.trim()).filter(Boolean) });
              notify.success(`Successfully created vector index ${create.name}.${saveNotice(CAP)}`); setCreate(null); idx.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create vector index</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Vector index name" description="3-63 characters: lowercase letters, numbers, hyphens and dots."><Input value={create.name} ariaLabel="Vector index name" onChange={({ detail: d }) => setCreate({ ...create, name: d.value })} /></FormField>
          <FormField label="Dimensions" description="1-4096. Every vector in the index must have exactly this many values."><Input value={create.dimension} ariaLabel="Dimensions" inputMode="numeric" onChange={({ detail: d }) => setCreate({ ...create, dimension: d.value })} /></FormField>
          <FormField label="Distance metric">
            <SegmentedControl selectedId={create.metric} onChange={({ detail: d }) => setCreate({ ...create, metric: d.selectedId })} options={[{ id: "cosine", text: "Cosine" }, { id: "euclidean", text: "Euclidean" }]} />
          </FormField>
          <FormField label="Non-filterable metadata keys (optional)" description="Comma-separated. Large keys (for example the source text) go here so they do not count toward the 2 KB filterable limit."><Input value={create.nonFilterable} ariaLabel="Non-filterable metadata keys" onChange={({ detail: d }) => setCreate({ ...create, nonFilterable: d.value })} /></FormField>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}

// ───────────────────────────── Vector buckets page ─────────────────────────────
export function VectorBuckets() {
  const notify = useNotify();
  const list = useAsync(() => v.listVectorBuckets(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [del, setDel] = useState(null);
  const [saving, setSaving] = useState(false);
  const rows = list.data || [];
  const cur = sel[0]?.vectorBucketName;
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id={CAP} title="Vector buckets" counter={`(${rows.length})`}
        description="Vector buckets store and search vector embeddings with similarity queries."
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={list.reload} />
          <Button ariaLabel="Delete vector bucket" disabled={sel.length !== 1} onClick={() => setDel({ name: cur, typed: "" })}>Delete</Button>
          <Button variant="primary" onClick={() => setCreate({ name: "", sse: "AES256", kms: "" })}>Create vector bucket</Button>
        </SpaceBetween>}>
        {list.loading ? <Loading /> : list.error ? <ErrorAlert error={list.error} />
          : <Table variant="embedded" items={rows} trackBy="vectorBucketName" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
              columnDefinitions={[
                { id: "n", header: "Name", cell: (b) => b.vectorBucketName },
                { id: "r", header: "AWS Region", cell: () => "US East (N. Virginia) us-east-1" },
                { id: "arn", header: "Vector bucket ARN", cell: (b) => b.vectorBucketArn },
                { id: "c", header: "Creation date", cell: (b) => when(b.creationTime) },
              ]}
              empty={<Empty title="No vector buckets">Create a vector bucket to start storing vector embeddings.</Empty>} />}
      </CapabilityContainer>
      {cur && <BucketDetail key={cur} name={cur} />}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create vector bucket"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} disabled={!create?.name} onClick={async () => {
            setSaving(true);
            try { await v.createVectorBucket(create.name, create.sse, create.kms); notify.success(`Successfully created vector bucket ${create.name}.${saveNotice(CAP)}`); setCreate(null); list.reload(); }
            catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create vector bucket</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Vector bucket name" description="3-63 characters: lowercase letters, numbers and hyphens. Must be unique in this Region."><Input value={create.name} ariaLabel="Vector bucket name" onChange={({ detail: d }) => setCreate({ ...create, name: d.value })} /></FormField>
          <FormField label="Encryption type">
            <SegmentedControl selectedId={create.sse} onChange={({ detail: d }) => setCreate({ ...create, sse: d.selectedId })} options={[{ id: "AES256", text: "SSE-S3" }, { id: "aws:kms", text: "SSE-KMS" }]} />
          </FormField>
          {create.sse === "aws:kms" && <FormField label="AWS KMS key ARN"><Input value={create.kms} ariaLabel="KMS key ARN" onChange={({ detail: d }) => setCreate({ ...create, kms: d.value })} /></FormField>}
        </SpaceBetween>}
      </Modal>
      <Modal visible={!!del} onDismiss={() => setDel(null)} header="Delete vector bucket"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setDel(null)}>Cancel</Button>
          <Button variant="primary" disabled={del?.typed !== del?.name} onClick={async () => {
            try { await v.deleteVectorBucket(del.name); notify.success(`Successfully deleted vector bucket ${del.name}.`); setDel(null); setSel([]); list.reload(); } catch (e) { notify.error(e); }
          }}>Delete vector bucket</Button>
        </SpaceBetween></Box>}>
        {del && <SpaceBetween size="m">
          <Alert type="warning">A vector bucket must have no vector indexes before it can be deleted.</Alert>
          <FormField label={`To confirm deletion, enter the vector bucket name (${del.name}).`}><Input value={del.typed} ariaLabel="Confirm vector bucket name" onChange={({ detail: d }) => setDel({ ...del, typed: d.value })} /></FormField>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}
