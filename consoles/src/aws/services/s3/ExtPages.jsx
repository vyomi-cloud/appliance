/* S3 sweep S3-4 sections: S3 Metadata (journal + live inventory), CloudTrail data events, Transfer acceleration,
 * bucket-level Storage Lens. Each wraps its own CapabilityContainer so the badge states what Vyomi does and does not do. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtBytes, KeyValue } from "../../kit/common.jsx";
import * as x from "./extApi.js";
import * as api from "./api.js";

const Loading = () => <StatusIndicator type="loading">Loading</StatusIndicator>;
const num = (n) => Number(n || 0).toLocaleString();

// ───────────────────────────── Transfer acceleration ─────────────────────────────
export function AccelerateSection({ bucket }) {
  const notify = useNotify();
  const acc = useAsync(() => x.getAccelerate(bucket), [bucket]);
  const [edit, setEdit] = useState(null);
  const [saving, setSaving] = useState(false);
  const status = acc.data?.status;
  return (
    <CapabilityContainer id="s3.bucket.accelerate" title="Transfer acceleration"
      actions={<Button data-testid="accel-edit" onClick={() => setEdit({ status: status === "Enabled" ? "Enabled" : "Suspended" })}>Edit</Button>}>
      {acc.loading ? <Loading /> : acc.error ? <ErrorAlert error={acc.error} />
        : <SpaceBetween size="s">
            <div><Box variant="awsui-key-label">Transfer acceleration</Box><div data-testid="accel-status">{status === "Enabled" ? "Enabled" : status === "Suspended" ? "Suspended" : "Disabled"}</div></div>
            {status === "Enabled" && <div><Box variant="awsui-key-label">Accelerated endpoint</Box><div>{bucket}.s3-accelerate.amazonaws.com</div></div>}
          </SpaceBetween>}
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header="Edit Transfer acceleration"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try {
              await x.putAccelerate(bucket, edit.status);
              notify.success(`Successfully edited Transfer acceleration.${saveNotice("s3.bucket.accelerate")}`);
              setEdit(null); acc.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <FormField label="Transfer acceleration" description="Vyomi has one local endpoint and no edge network: enabling this is stored and accepted on the s3-accelerate host name, but nothing is made faster.">
          <RadioGroup value={edit.status} onChange={({ detail }) => setEdit({ ...edit, status: detail.value })}
            items={[{ value: "Suspended", label: "Suspend" }, { value: "Enabled", label: "Enable" }]} />
        </FormField>}
      </Modal>
    </CapabilityContainer>
  );
}

// ───────────────────────────── CloudTrail data events ─────────────────────────────
export function DataEventsSection({ bucket }) {
  const notify = useNotify();
  const ev = useAsync(() => x.dataEvents(bucket, { limit: 50 }), [bucket]);
  const [create, setCreate] = useState(null);
  const [saving, setSaving] = useState(false);
  const trails = ev.data?.trails || [];
  const events = ev.data?.events || [];
  const act = async (fn, msg) => { try { await fn(); notify.success(msg); ev.reload(); } catch (e) { notify.error(e); } };
  return (
    <CapabilityContainer id="s3.bucket.cloudtrail-data-events" title="AWS CloudTrail data events"
      description="Trails that log object-level (data) events for this bucket, and the events Vyomi has recorded."
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button iconName="refresh" onClick={ev.reload}>Refresh</Button>
        <Button data-testid="trail-configure" onClick={() => setCreate({ name: `${bucket}-data-events`.slice(0, 60), dest: "", readWrite: "All" })}>Configure in CloudTrail</Button>
      </SpaceBetween>}>
      {ev.loading ? <Loading /> : ev.error ? <ErrorAlert error={ev.error} />
        : <SpaceBetween size="l">
            <Table variant="embedded" data-testid="trail-table" items={trails} trackBy="name"
              empty={<Box textAlign="center" color="inherit"><b>No trail logs data events for this bucket</b></Box>}
              header={<Box variant="h3">Trails ({trails.length})</Box>}
              columnDefinitions={[
                { id: "name", header: "Trail name", cell: (t) => t.name },
                { id: "dest", header: "Log destination bucket", cell: (t) => t.s3Bucket },
                { id: "rw", header: "Event type", cell: (t) => (t.advanced ? "Advanced selectors" : t.readWriteType === "All" ? "Read and write" : t.readWriteType === "ReadOnly" ? "Read" : "Write") },
                { id: "st", header: "Status", cell: (t) => <StatusIndicator type={t.logging ? "success" : "stopped"}>{t.logging ? "Logging" : "Not logging"}</StatusIndicator> },
                { id: "act", header: "Actions", cell: (t) => (
                  <SpaceBetween direction="horizontal" size="xs">
                    {t.logging
                      ? <Button variant="inline-link" onClick={() => act(() => x.stopTrail(t.name), `Stopped logging for ${t.name}.`)}>Stop logging</Button>
                      : <Button variant="inline-link" onClick={() => act(() => x.startTrail(t.name), `Started logging for ${t.name}.`)}>Start logging</Button>}
                    <Button variant="inline-link" onClick={() => act(() => x.deleteTrail(t.name), `Deleted trail ${t.name}.`)}>Delete trail</Button>
                  </SpaceBetween>) },
              ]} />
            <Table variant="embedded" data-testid="events-table" items={events} trackBy="eventID"
              empty={<Box textAlign="center" color="inherit"><b>No data events recorded</b><Box variant="p" color="inherit">Events appear here once a logging trail covers this bucket and requests are served.</Box></Box>}
              header={<Box variant="h3">Recorded data events ({num(ev.data.total)}{events.length < ev.data.total ? `, showing latest ${events.length}` : ""})</Box>}
              columnDefinitions={[
                { id: "t", header: "Event time", cell: (e) => e.eventTime },
                { id: "n", header: "Event name", cell: (e) => e.eventName },
                { id: "k", header: "Object", cell: (e) => e.requestParameters.key || "-" },
                { id: "ro", header: "Read-only", cell: (e) => String(e.readOnly) },
                { id: "tr", header: "Trails", cell: (e) => (e.vyomi?.trails || []).join(", ") },
                { id: "err", header: "Error code", cell: (e) => e.errorCode || "-" },
              ]} />
          </SpaceBetween>}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Configure CloudTrail data events"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} disabled={!create?.name || !create?.dest} onClick={async () => {
            setSaving(true);
            try {
              await x.createDataTrail({ name: create.name, destBucket: create.dest, bucket, readWrite: create.readWrite });
              notify.success(`Successfully created trail ${create.name}.${saveNotice("s3.bucket.cloudtrail-data-events")}`);
              setCreate(null); ev.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create trail</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Trail name"><Input value={create.name} onChange={({ detail }) => setCreate({ ...create, name: detail.value })} /></FormField>
          <FormField label="Log destination bucket" description="An existing bucket. Vyomi records the events but does not deliver log files to it.">
            <Input value={create.dest} placeholder="my-trail-logs" onChange={({ detail }) => setCreate({ ...create, dest: detail.value })} /></FormField>
          <FormField label="Event type">
            <RadioGroup value={create.readWrite} onChange={({ detail }) => setCreate({ ...create, readWrite: detail.value })}
              items={[{ value: "All", label: "Read and write" }, { value: "ReadOnly", label: "Read" }, { value: "WriteOnly", label: "Write" }]} />
          </FormField>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

// ───────────────────────────── S3 Metadata ─────────────────────────────
export function MetadataSection({ bucket }) {
  const notify = useNotify();
  const cfg = useAsync(() => x.getMetadataConfig(bucket), [bucket]);
  const [table, setTable] = useState("journal");
  const [recordType, setRecordType] = useState("");
  const [prefix, setPrefix] = useState("");
  const rows = useAsync(() => (cfg.data?.configured ? x.metadataRecords(bucket, { table, recordType, prefix, limit: 100 }) : Promise.resolve(null)), [bucket, table, recordType, prefix, cfg.data?.configured, cfg.data?.inventory?.state]);
  const [create, setCreate] = useState(null);
  const [saving, setSaving] = useState(false);
  const c = cfg.data;
  const refresh = () => { cfg.reload(); rows.reload(); };
  const cols = rows.data?.columns || [];
  return (
    <CapabilityContainer id="s3.bucket.metadata-configuration" title="Metadata configuration"
      description="Journal and live inventory tables describing the objects in this bucket."
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button iconName="refresh" onClick={refresh}>Refresh</Button>
        {c?.configured
          ? <Button data-testid="meta-delete" onClick={async () => { try { await x.deleteMetadataConfig(bucket); notify.success("Successfully deleted metadata configuration."); refresh(); } catch (e) { notify.error(e); } }}>Delete configuration</Button>
          : <Button variant="primary" data-testid="meta-create" onClick={() => setCreate({ expire: false, days: "30", inventory: true })}>Create metadata configuration</Button>}
      </SpaceBetween>}>
      {cfg.loading ? <Loading /> : cfg.error ? <ErrorAlert error={cfg.error} />
        : !c.configured ? <Box color="text-body-secondary" data-testid="meta-empty">No metadata configuration. Create one to record a journal of object changes and a live inventory of this bucket.</Box>
        : <SpaceBetween size="l">
            <KeyValue title="Configuration" columns={3} items={[
              ["Destination table bucket", c.destination.TableBucketArn], ["Namespace", c.destination.TableNamespace],
              ["Journal table", `${c.journal.name} (${c.journal.status})`],
              ["Journal record expiration", c.journal.expiration === "ENABLED" ? `Enabled, ${c.journal.days} days` : "Disabled"],
              ["Live inventory table", c.inventory.state === "ENABLED" ? `${c.inventory.name} (${c.inventory.status})` : "Disabled"]]} />
            <SpaceBetween direction="horizontal" size="xs">
              <Button data-testid="meta-toggle-inventory" onClick={async () => { try { await x.updateInventoryTable(bucket, c.inventory.state !== "ENABLED"); notify.success("Successfully updated live inventory table."); refresh(); } catch (e) { notify.error(e); } }}>
                {c.inventory.state === "ENABLED" ? "Disable live inventory table" : "Enable live inventory table"}</Button>
            </SpaceBetween>
            <SpaceBetween size="s">
              <SpaceBetween direction="horizontal" size="xs">
                <Select selectedOption={{ value: table, label: table === "journal" ? "Journal table" : "Live inventory table" }} onChange={({ detail }) => setTable(detail.selectedOption.value)}
                  options={[{ value: "journal", label: "Journal table" }, { value: "inventory", label: "Live inventory table" }]} />
                {table === "journal" && <Select selectedOption={{ value: recordType, label: recordType || "All record types" }} onChange={({ detail }) => setRecordType(detail.selectedOption.value)}
                  options={[{ value: "", label: "All record types" }, { value: "CREATE", label: "CREATE" }, { value: "DELETE", label: "DELETE" }]} />}
                <Input value={prefix} placeholder="Key prefix" onChange={({ detail }) => setPrefix(detail.value)} />
              </SpaceBetween>
              {rows.loading ? <Loading /> : rows.error ? <ErrorAlert error={rows.error} />
                : <Table variant="embedded" data-testid="meta-table" items={rows.data?.rows || []} trackBy={(r) => `${r.sequence_number}`}
                    header={<Box variant="h3">{table === "journal" ? "Journal records" : "Live inventory"} ({num(rows.data?.total)})</Box>}
                    empty={<Box textAlign="center" color="inherit"><b>{table === "inventory" && !rows.data?.tableEnabled ? "The live inventory table is disabled" : "No records"}</b></Box>}
                    columnDefinitions={["key", ...(table === "journal" ? ["record_type", "record_timestamp"] : ["is_latest"]), "version_id", "size", "e_tag", "storage_class", "sequence_number"]
                      .filter((k) => cols.includes(k) || k === "is_latest").map((k) => ({ id: k, header: k, cell: (r) => (r[k] === null || r[k] === undefined ? "-" : String(r[k])) }))} />}
            </SpaceBetween>
          </SpaceBetween>}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create metadata configuration"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={async () => {
            setSaving(true);
            try {
              await x.createMetadataConfig(bucket, create);
              notify.success(`Successfully created metadata configuration.${saveNotice("s3.bucket.metadata-configuration")}`);
              setCreate(null); refresh();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create configuration</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <Checkbox checked={create.expire} onChange={({ detail }) => setCreate({ ...create, expire: detail.checked })}>Enable journal table record expiration</Checkbox>
          {create.expire && <FormField label="Days (minimum 7)"><Input type="number" value={create.days} onChange={({ detail }) => setCreate({ ...create, days: detail.value })} /></FormField>}
          <Checkbox checked={create.inventory} onChange={({ detail }) => setCreate({ ...create, inventory: detail.checked })}>Enable live inventory table</Checkbox>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

// ───────────────────────────── bucket-level Storage Lens ─────────────────────────────
export function BucketLensSection({ bucket }) {
  const lens = useAsync(() => x.bucketLens(bucket), [bucket]);
  const d = lens.data;
  return (
    <CapabilityContainer id="s3.bucket.storage-lens" title="Storage Lens metrics"
      description="Storage and request activity for this bucket, computed from the live object store and the requests Vyomi has served."
      actions={<Button iconName="refresh" onClick={lens.reload}>Refresh</Button>}>
      {lens.loading ? <Loading /> : lens.error ? <ErrorAlert error={lens.error} />
        : <SpaceBetween size="l" data-testid="bucket-lens">
            <KeyValue title="Storage" columns={4} items={[
              ["Total storage", <span data-testid="lens-total">{fmtBytes(d.storage.totalBytes)}</span>], ["Current version bytes", fmtBytes(d.storage.currentBytes)],
              ["Object count (current)", <span data-testid="lens-objects">{num(d.storage.currentObjects)}</span>], ["Noncurrent version bytes", fmtBytes(d.storage.noncurrentBytes)],
              ["Noncurrent objects", num(d.storage.noncurrentObjects)], ["Delete markers", num(d.storage.deleteMarkers)],
              ["Incomplete multipart upload bytes", fmtBytes(d.storage.incompleteMpuBytes)], ["% current version bytes", `${d.storage.currentVersionPct}%`],
              ["Average object size", fmtBytes(d.storage.avgObjectBytes)]]} />
            <KeyValue title="Request activity (served by Vyomi)" columns={4} items={[
              ["All requests", <span data-testid="lens-all">{num(d.activity.AllRequests)}</span>], ["GET", num(d.activity.GetRequests)], ["PUT", num(d.activity.PutRequests)],
              ["HEAD", num(d.activity.HeadRequests)], ["DELETE", num(d.activity.DeleteRequests)], ["LIST", num(d.activity.ListRequests)],
              ["Bytes uploaded", fmtBytes(d.activity.BytesUploaded)], ["Bytes downloaded", fmtBytes(d.activity.BytesDownloaded)],
              ["4xx errors", `${num(d.activity["4xxErrors"])} (${d.activity.errorRatePct4xx}%)`], ["5xx errors", `${num(d.activity["5xxErrors"])} (${d.activity.errorRatePct5xx}%)`]]} />
            <Table variant="embedded" items={d.byStorageClass} trackBy="storageClass" header={<Box variant="h3">By storage class</Box>}
              empty={<Box textAlign="center" color="inherit"><b>No objects</b></Box>}
              columnDefinitions={[{ id: "c", header: "Storage class", cell: (r) => r.storageClass }, { id: "b", header: "Storage", cell: (r) => fmtBytes(r.bytes) }, { id: "o", header: "Objects", cell: (r) => num(r.objects) }]} />
            <Table variant="embedded" items={d.topPrefixes} trackBy="prefix" header={<Box variant="h3">Top prefixes (current versions)</Box>}
              empty={<Box textAlign="center" color="inherit"><b>No objects</b></Box>}
              columnDefinitions={[{ id: "p", header: "Prefix", cell: (r) => r.prefix }, { id: "b", header: "Storage", cell: (r) => fmtBytes(r.bytes) }, { id: "o", header: "Objects", cell: (r) => num(r.objects) }]} />
          </SpaceBetween>}
    </CapabilityContainer>
  );
}
