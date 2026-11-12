/* S3 account-level pages backed by the shared core (sweep S3-2): Multi-Region Access Points,
 * Access Grants and Batch Operations. Each is a CapabilityContainer (registry ids s3.account.*). */
import { useEffect, useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import Multiselect from "@cloudscape-design/components/multiselect";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import Wizard from "@cloudscape-design/components/wizard";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtDate, KeyValue } from "../../kit/common.jsx";
import * as api from "./api.js";
import * as sw from "./sweepApi.js";

const opt = (v, label = v, extra = {}) => ({ value: v, label, ...extra });
const Loading = () => <StatusIndicator type="loading">Loading</StatusIndicator>;
const ROLE = "arn:aws:iam::123456789012:role/batch-operations-role";

// ────────────────────────── Multi-Region Access Points ──────────────────────────
export function MultiRegionAccessPoints() {
  const notify = useNotify();
  const list = useAsync(() => sw.listMrap(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [saving, setSaving] = useState(false);
  const [dials, setDials] = useState(null);
  const [policy, setPolicy] = useState("");
  const name = sel[0]?.name;
  const detail = useAsync(async () => (name ? sw.getMrapDetail(name) : null), [name]);
  const bkts = useAsync(() => sw.bucketsWithRegion(), []);
  useEffect(() => { setDials(detail.data ? detail.data.routes.map((r) => ({ ...r })) : null); }, [detail.data]);
  useEffect(() => { setPolicy(detail.data?.policy || ""); }, [detail.data?.name]);   // eslint-disable-line react-hooks/exhaustive-deps
  const rows = list.data || [];
  const act = async (fn, ok, after) => { try { await fn(); notify.success(ok); after && after(); } catch (e) { notify.error(e); } };
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="s3.account.multi-region-access-points" title="Multi-Region Access Points" counter={`(${rows.length})`}
        description="A Multi-Region Access Point provides a global endpoint that routes requests to buckets in different AWS Regions."
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={() => { list.reload(); detail.reload(); }} />
          <Button disabled={sel.length !== 1} onClick={() => act(() => sw.deleteMrap(name), `Successfully deleted Multi-Region Access Point ${name}.`, () => { setSel([]); list.reload(); })}>Delete</Button>
          <Button variant="primary" onClick={() => { bkts.reload(); setCreate({ name: "", buckets: [] }); }}>Create Multi-Region Access Point</Button>
        </SpaceBetween>}>
        {list.loading ? <Loading /> : list.error ? <ErrorAlert error={list.error} />
          : <Table variant="embedded" items={rows} trackBy="name" selectionType="single" selectedItems={sel} onSelectionChange={({ detail: d }) => setSel(d.selectedItems)}
              columnDefinitions={[
                { id: "n", header: "Name", cell: (a) => a.name },
                { id: "al", header: "Alias", cell: (a) => a.alias },
                { id: "s", header: "Status", cell: (a) => <StatusIndicator type={a.status === "READY" ? "success" : "pending"}>{a.status}</StatusIndicator> },
                { id: "r", header: "Regions", cell: (a) => a.regions.map((r) => r.region).join(", ") },
                { id: "arn", header: "ARN", cell: (a) => a.arn },
              ]}
              empty={<Box textAlign="center" color="inherit"><b>No Multi-Region Access Points</b><Box variant="p" color="inherit">Create one over buckets in different Regions.</Box></Box>} />}
      </CapabilityContainer>
      {name && detail.data && (
        <CapabilityContainer id="s3.account.multi-region-access-points" title={`Details - ${name}`}>
          <SpaceBetween size="m">
            <KeyValue items={[["Alias", detail.data.alias], ["ARN", detail.data.arn], ["Status", detail.data.status], ["Created", fmtDate(detail.data.created)]]} />
            <Table variant="embedded" header={<Header variant="h3" actions={<Button onClick={() => act(() => sw.submitMrapRoutes(detail.data.arn, dials), "Successfully updated traffic dials.", detail.reload)}>Save traffic dials</Button>}>Replication and failover - traffic dials</Header>} items={dials || []} trackBy="bucket"
              columnDefinitions={[
                { id: "b", header: "Bucket", cell: (r) => r.bucket },
                { id: "rg", header: "Region", cell: (r) => r.region },
                { id: "d", header: "Traffic dial (%)", cell: (r) => (
                  <Input type="number" value={String(r.dial)} ariaLabel={`Traffic dial ${r.bucket}`} onChange={({ detail: d }) => setDials(dials.map((x) => (x === r ? { ...x, dial: Math.max(0, Math.min(100, Number(d.value) || 0)) } : x)))} />) },
                { id: "st", header: "Status", cell: (r) => <StatusIndicator type={r.dial > 0 ? "success" : "stopped"}>{r.dial > 0 ? "Active" : "Passive"}</StatusIndicator> },
              ]} />
            <FormField label="Multi-Region Access Point policy" description="Stored and returned; Vyomi never evaluates it against a caller.">
              <Textarea value={policy} rows={6} ariaLabel="Policy" onChange={({ detail: d }) => setPolicy(d.value)} />
            </FormField>
            <Button disabled={!policy.trim()} onClick={() => act(() => sw.putMrapPolicy(name, policy), `Successfully saved the policy.${saveNotice("s3.account.multi-region-access-points")}`, detail.reload)}>Save policy</Button>
          </SpaceBetween>
        </CapabilityContainer>
      )}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create Multi-Region Access Point" size="large"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} disabled={!create?.name || !create?.buckets.length} onClick={async () => {
            setSaving(true);
            try {
              const r = await sw.createMrap(create.name, create.buckets.map((b) => b.value));
              notify.success(`Multi-Region Access Point ${create.name} creation ${String(r.status).toLowerCase()}.${saveNotice("s3.account.multi-region-access-points")}`);
              setCreate(null); list.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create Multi-Region Access Point</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Multi-Region Access Point name" description="3-50 characters: lowercase letters, numbers and hyphens."><Input value={create.name} onChange={({ detail: d }) => setCreate({ ...create, name: d.value })} ariaLabel="Multi-Region Access Point name" /></FormField>
          <FormField label="Buckets" description="One bucket per Region. Each bucket can belong to a single Multi-Region Access Point.">
            <Multiselect selectedOptions={create.buckets} options={(bkts.data || []).map((b) => opt(b.name, b.name, { description: b.region }))} placeholder="Choose buckets" empty="No buckets"
              onChange={({ detail: d }) => setCreate({ ...create, buckets: d.selectedOptions })} ariaLabel="Buckets" />
          </FormField>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}

// ────────────────────────── Access Grants ──────────────────────────
export function AccessGrants() {
  const notify = useNotify();
  const inst = useAsync(() => sw.getAccessGrantsInstance(), []);
  const locs = useAsync(async () => (await sw.getAccessGrantsInstance() ? sw.listAccessGrantsLocations() : []), []);
  const grants = useAsync(async () => (await sw.getAccessGrantsInstance() ? sw.listAccessGrants() : []), []);
  const bkts = useAsync(() => api.listBuckets(), []);
  const [selL, setSelL] = useState([]);
  const [selG, setSelG] = useState([]);
  const [newLoc, setNewLoc] = useState(null);
  const [newGrant, setNewGrant] = useState(null);
  const [creds, setCreds] = useState(null);
  const all = () => { inst.reload(); locs.reload(); grants.reload(); };
  const act = async (fn, ok, after) => { try { await fn(); notify.success(ok); after ? after() : all(); } catch (e) { notify.error(e); } };
  const i = inst.data;
  const L = locs.data || [];
  const G = grants.data || [];
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="s3.account.access-grants" title="S3 Access Grants instance"
        description="S3 Access Grants maps identities to S3 locations and vends scoped temporary credentials."
        actions={i ? <Button onClick={() => act(() => sw.deleteAccessGrantsInstance(), "Successfully deleted the S3 Access Grants instance.")}>Delete instance</Button>
          : <Button variant="primary" onClick={() => act(() => sw.createAccessGrantsInstance(), `Successfully created the S3 Access Grants instance.${saveNotice("s3.account.access-grants")}`)}>Create S3 Access Grants instance</Button>}>
        {inst.loading ? <Loading /> : inst.error ? <ErrorAlert error={inst.error} />
          : i ? <KeyValue items={[["Instance ARN", i.arn], ["Instance ID", i.id], ["Created", fmtDate(i.created)], ["IAM Identity Center", i.idc || "Not associated"]]} />
            : <Box textAlign="center" color="inherit"><b>No S3 Access Grants instance</b><Box variant="p" color="inherit">Create an instance in this Region to register locations and grants.</Box></Box>}
      </CapabilityContainer>
      {i && (
        <CapabilityContainer id="s3.account.access-grants" title="Locations" counter={`(${L.length})`}
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button disabled={selL.length !== 1} onClick={() => act(() => sw.deleteAccessGrantsLocation(selL[0].id), "Successfully deleted the location.", () => { setSelL([]); all(); })}>Delete</Button>
            <Button variant="primary" onClick={() => setNewLoc({ bucket: "", prefix: "", role: ROLE })}>Register location</Button>
          </SpaceBetween>}>
          {locs.loading ? <Loading /> : locs.error ? <ErrorAlert error={locs.error} />
            : <Table variant="embedded" items={L} trackBy="id" selectionType="single" selectedItems={selL} onSelectionChange={({ detail: d }) => setSelL(d.selectedItems)}
                columnDefinitions={[
                  { id: "s", header: "Location scope", cell: (l) => l.scope },
                  { id: "r", header: "IAM role", cell: (l) => l.role },
                  { id: "id", header: "Location ID", cell: (l) => l.id },
                ]}
                empty={<Box textAlign="center" color="inherit"><b>No locations</b></Box>} />}
        </CapabilityContainer>
      )}
      {i && (
        <CapabilityContainer id="s3.account.access-grants" title="Grants" counter={`(${G.length})`}
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button disabled={selG.length !== 1} onClick={async () => {
              try { const g = selG[0]; setCreds(await sw.getDataAccess(g.scope.endsWith("*") ? g.scope : g.scope, g.permission === "READWRITE" ? "READ" : g.permission)); } catch (e) { notify.error(e); }
            }}>Get temporary credentials</Button>
            <Button disabled={selG.length !== 1} onClick={() => act(() => sw.deleteAccessGrant(selG[0].id), "Successfully deleted the grant.", () => { setSelG([]); all(); })}>Delete</Button>
            <Button variant="primary" disabled={!L.length} onClick={() => setNewGrant({ locationId: L[0].id, sub: "*", granteeType: "IAM", grantee: "arn:aws:iam::123456789012:role/app", permission: "READ" })}>Create grant</Button>
          </SpaceBetween>}>
          {grants.loading ? <Loading /> : grants.error ? <ErrorAlert error={grants.error} />
            : <Table variant="embedded" items={G} trackBy="id" selectionType="single" selectedItems={selG} onSelectionChange={({ detail: d }) => setSelG(d.selectedItems)}
                columnDefinitions={[
                  { id: "g", header: "Grantee", cell: (g) => g.grantee },
                  { id: "p", header: "Permission", cell: (g) => g.permission },
                  { id: "s", header: "Grant scope", cell: (g) => g.scope },
                  { id: "id", header: "Grant ID", cell: (g) => g.id },
                ]}
                empty={<Box textAlign="center" color="inherit"><b>No grants</b><Box variant="p" color="inherit">{L.length ? "Create a grant on a registered location." : "Register a location first."}</Box></Box>} />}
        </CapabilityContainer>
      )}
      <Modal visible={!!newLoc} onDismiss={() => setNewLoc(null)} header="Register location"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setNewLoc(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            const f = newLoc;
            const scope = f.bucket ? `s3://${f.bucket}${f.prefix ? `/${f.prefix.replace(/\*$/, "")}*` : ""}` : "s3://";
            await act(() => sw.createAccessGrantsLocation(scope, f.role), `Successfully registered location ${scope}.${saveNotice("s3.account.access-grants")}`);
            setNewLoc(null);
          }}>Register location</Button>
        </SpaceBetween></Box>}>
        {newLoc && <SpaceBetween size="m">
          <FormField label="Bucket" description="Leave empty for the default location (s3://, every bucket).">
            <Select selectedOption={newLoc.bucket ? opt(newLoc.bucket) : null} options={(bkts.data || []).map((b) => opt(b.name))} placeholder="Default location (s3://)" onChange={({ detail: d }) => setNewLoc({ ...newLoc, bucket: d.selectedOption.value })} ariaLabel="Location bucket" />
          </FormField>
          <FormField label="Prefix (optional)"><Input value={newLoc.prefix} onChange={({ detail: d }) => setNewLoc({ ...newLoc, prefix: d.value })} ariaLabel="Location prefix" /></FormField>
          <FormField label="IAM role ARN"><Input value={newLoc.role} onChange={({ detail: d }) => setNewLoc({ ...newLoc, role: d.value })} ariaLabel="IAM role ARN" /></FormField>
        </SpaceBetween>}
      </Modal>
      <Modal visible={!!newGrant} onDismiss={() => setNewGrant(null)} header="Create grant"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setNewGrant(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            const f = newGrant;
            await act(() => sw.createAccessGrant({ locationId: f.locationId, subPrefix: f.sub, granteeType: f.granteeType, grantee: f.grantee, permission: f.permission }), `Successfully created the grant.${saveNotice("s3.account.access-grants")}`);
            setNewGrant(null);
          }}>Create grant</Button>
        </SpaceBetween></Box>}>
        {newGrant && <SpaceBetween size="m">
          <FormField label="Location"><Select selectedOption={opt(newGrant.locationId, L.find((l) => l.id === newGrant.locationId)?.scope || newGrant.locationId)} options={L.map((l) => opt(l.id, l.scope))} onChange={({ detail: d }) => setNewGrant({ ...newGrant, locationId: d.selectedOption.value })} ariaLabel="Grant location" /></FormField>
          <FormField label="Sub-prefix" description="Appended to the location scope, e.g. reports/* "><Input value={newGrant.sub} onChange={({ detail: d }) => setNewGrant({ ...newGrant, sub: d.value })} ariaLabel="Sub-prefix" /></FormField>
          <FormField label="Grantee type"><Select selectedOption={opt(newGrant.granteeType)} options={["IAM", "DIRECTORY_USER", "DIRECTORY_GROUP"].map((x) => opt(x))} onChange={({ detail: d }) => setNewGrant({ ...newGrant, granteeType: d.selectedOption.value })} ariaLabel="Grantee type" /></FormField>
          <FormField label="Grantee"><Input value={newGrant.grantee} onChange={({ detail: d }) => setNewGrant({ ...newGrant, grantee: d.value })} ariaLabel="Grantee" /></FormField>
          <FormField label="Permission"><Select selectedOption={opt(newGrant.permission)} options={["READ", "WRITE", "READWRITE"].map((x) => opt(x))} onChange={({ detail: d }) => setNewGrant({ ...newGrant, permission: d.selectedOption.value })} ariaLabel="Permission" /></FormField>
        </SpaceBetween>}
      </Modal>
      <Modal visible={!!creds} onDismiss={() => setCreds(null)} header="Temporary credentials (GetDataAccess)"
        footer={<Box float="right"><Button variant="primary" onClick={() => setCreds(null)}>Close</Button></Box>}>
        {creds && <KeyValue items={[["Matched grant target", creds.matched], ["Access key ID", creds.accessKeyId], ["Secret access key", creds.secretAccessKey], ["Session token", creds.sessionToken.slice(0, 24) + "..."], ["Expires", creds.expiration]]} />}
      </Modal>
    </SpaceBetween>
  );
}

// ────────────────────────── Batch Operations ──────────────────────────
const statusType = (s) => ({ Complete: "success", Failed: "error", Cancelled: "stopped", Active: "in-progress", Ready: "pending", Suspended: "warning", Preparing: "in-progress" }[s] || "info");
const ACLS = ["private", "public-read", "public-read-write", "authenticated-read", "bucket-owner-read", "bucket-owner-full-control"];

function NewJobWizard({ onDone, onCancel }) {
  const notify = useNotify();
  const bkts = useAsync(() => api.listBuckets(), []);
  const fns = useAsync(() => sw.listLambdaFunctions().catch(() => []), []);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({
    format: "S3BatchOperations_CSV_20180820", mBucket: "", mKey: "", csv: "",
    operation: "S3PutObjectCopy", targetBucket: "", targetPrefix: "", storageClass: "", functionArn: "", tags: "env=prod", acl: "private", days: "1", tier: "STANDARD", hold: "ON", mode: "GOVERNANCE", until: "2099-01-01",
    priority: "10", description: "", confirm: true, reportOn: true, rBucket: "", rPrefix: "batch-reports", scope: "AllTasks", role: ROLE,
  });
  const set = (k) => ({ detail }) => setF({ ...f, [k]: detail.value });
  const sel = (k) => ({ detail }) => setF({ ...f, [k]: detail.selectedOption.value });
  const B = (bkts.data || []).map((b) => opt(b.name));
  const bsel = (v) => (v ? opt(v) : null);
  const op = sw.BATCH_OPERATIONS.find((o) => o.value === f.operation);
  const params = () => ({
    targetBucket: f.targetBucket, targetPrefix: f.targetPrefix, storageClass: f.storageClass, functionArn: f.functionArn,
    tags: f.tags.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [k, ...v] = l.split("="); return { key: k.trim(), value: v.join("=").trim() }; }),
    acl: f.acl, days: f.days, tier: f.tier, hold: f.hold, mode: f.mode, until: f.until,
  });
  const submit = async () => {
    setBusy(true);
    try {
      if (f.csv.trim()) await api.putObject(f.mBucket, f.mKey, f.csv, "text/csv");
      const id = await sw.createJob({
        operation: f.operation, params: params(), priority: Number(f.priority), description: f.description, confirm: f.confirm, role: f.role,
        manifest: { bucket: f.mBucket, key: f.mKey, format: f.format, fields: f.format === "S3BatchOperations_CSV_20180820" ? ["Bucket", "Key"] : ["Bucket", "Key"] },
        report: { enabled: f.reportOn, bucket: f.rBucket, prefix: f.rPrefix, scope: f.scope },
      });
      notify.success(`Successfully created job ${id}.${saveNotice("s3.account.batch-operations")}`);
      onDone(id);
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  const manifestOk = f.mBucket && f.mKey;
  const opOk = f.operation === "S3PutObjectCopy" ? !!f.targetBucket : f.operation === "LambdaInvoke" ? !!f.functionArn : true;
  const steps = [
    { title: "Choose manifest", isOptional: false,
      content: <CapabilityContainer id="s3.account.batch-operations" title="Manifest"><SpaceBetween size="m">
        <FormField label="Manifest format"><Select selectedOption={opt(f.format, f.format === "S3BatchOperations_CSV_20180820" ? "S3 Batch Operations CSV (bucket,key[,version])" : "S3 Inventory report (CSV)")} onChange={sel("format")} ariaLabel="Manifest format"
          options={[opt("S3BatchOperations_CSV_20180820", "S3 Batch Operations CSV (bucket,key[,version])"), opt("S3InventoryReport_CSV_20161130", "S3 Inventory report (CSV)")]} /></FormField>
        <FormField label="Manifest bucket"><Select selectedOption={bsel(f.mBucket)} options={B} placeholder="Choose a bucket" onChange={sel("mBucket")} ariaLabel="Manifest bucket" /></FormField>
        <FormField label="Manifest object key"><Input value={f.mKey} onChange={set("mKey")} placeholder="manifests/objects.csv" ariaLabel="Manifest object key" /></FormField>
        <FormField label="Create the manifest object from CSV (optional)" description="Lines of bucket,key. Written to the key above before the job is created.">
          <Textarea value={f.csv} rows={4} onChange={set("csv")} ariaLabel="Manifest CSV content" /></FormField>
      </SpaceBetween></CapabilityContainer> },
    { title: "Choose operation",
      content: <CapabilityContainer id="s3.account.batch-operations" title="Operation"><SpaceBetween size="m">
        <FormField label="Operation" description={op?.description}><Select selectedOption={opt(op.value, op.label)} options={sw.BATCH_OPERATIONS.map((o) => opt(o.value, o.label, { description: o.description }))} onChange={sel("operation")} ariaLabel="Operation" /></FormField>
        {f.operation === "S3PutObjectCopy" && <>
          <FormField label="Destination bucket"><Select selectedOption={bsel(f.targetBucket)} options={B} placeholder="Choose a bucket" onChange={sel("targetBucket")} ariaLabel="Destination bucket" /></FormField>
          <FormField label="Destination key prefix (optional)"><Input value={f.targetPrefix} onChange={set("targetPrefix")} ariaLabel="Destination key prefix" /></FormField>
          <FormField label="Storage class (optional)"><Select selectedOption={opt(f.storageClass, f.storageClass || "Same as source")} options={["", "STANDARD", "STANDARD_IA", "ONEZONE_IA", "GLACIER", "DEEP_ARCHIVE"].map((x) => opt(x, x || "Same as source"))} onChange={sel("storageClass")} ariaLabel="Storage class" /></FormField></>}
        {f.operation === "LambdaInvoke" && <FormField label="Lambda function"><Select selectedOption={(fns.data || []).map((x) => opt(x.arn, x.name)).find((o) => o.value === f.functionArn) || null} options={(fns.data || []).map((x) => opt(x.arn, x.name))} placeholder="Choose a function" empty="No Lambda functions" onChange={sel("functionArn")} ariaLabel="Lambda function" /></FormField>}
        {f.operation === "S3PutObjectTagging" && <FormField label="Tags" description="One key=value per line."><Textarea value={f.tags} rows={3} onChange={set("tags")} ariaLabel="Tags" /></FormField>}
        {f.operation === "S3PutObjectAcl" && <FormField label="Canned ACL"><Select selectedOption={opt(f.acl)} options={ACLS.map((x) => opt(x))} onChange={sel("acl")} ariaLabel="Canned ACL" /></FormField>}
        {f.operation === "S3InitiateRestoreObject" && <><FormField label="Days to keep the restored copy"><Input type="number" value={f.days} onChange={set("days")} ariaLabel="Restore days" /></FormField>
          <FormField label="Retrieval tier"><Select selectedOption={opt(f.tier)} options={["STANDARD", "BULK"].map((x) => opt(x))} onChange={sel("tier")} ariaLabel="Retrieval tier" /></FormField></>}
        {f.operation === "S3PutObjectLegalHold" && <FormField label="Legal hold"><Select selectedOption={opt(f.hold)} options={["ON", "OFF"].map((x) => opt(x))} onChange={sel("hold")} ariaLabel="Legal hold" /></FormField>}
        {f.operation === "S3PutObjectRetention" && <><FormField label="Retention mode"><Select selectedOption={opt(f.mode)} options={["GOVERNANCE", "COMPLIANCE"].map((x) => opt(x))} onChange={sel("mode")} ariaLabel="Retention mode" /></FormField>
          <FormField label="Retain until"><Input value={f.until} onChange={set("until")} placeholder="2099-01-01" ariaLabel="Retain until" /></FormField></>}
      </SpaceBetween></CapabilityContainer> },
    { title: "Configure additional options",
      content: <CapabilityContainer id="s3.account.batch-operations" title="Additional options"><SpaceBetween size="m">
        <FormField label="Description"><Input value={f.description} onChange={set("description")} ariaLabel="Description" /></FormField>
        <FormField label="Priority" description="Higher numbers run first."><Input type="number" value={f.priority} onChange={set("priority")} ariaLabel="Priority" /></FormField>
        <Checkbox checked={f.confirm} onChange={({ detail }) => setF({ ...f, confirm: detail.checked })}>Require confirmation to run this job</Checkbox>
        <Checkbox checked={f.reportOn} onChange={({ detail }) => setF({ ...f, reportOn: detail.checked })}>Generate a completion report</Checkbox>
        {f.reportOn && <>
          <FormField label="Completion report bucket"><Select selectedOption={bsel(f.rBucket)} options={B} placeholder="Choose a bucket" onChange={sel("rBucket")} ariaLabel="Report bucket" /></FormField>
          <FormField label="Report prefix"><Input value={f.rPrefix} onChange={set("rPrefix")} ariaLabel="Report prefix" /></FormField>
          <FormField label="Tasks to report"><Select selectedOption={opt(f.scope, f.scope === "AllTasks" ? "All tasks" : "Failed tasks only")} options={[opt("AllTasks", "All tasks"), opt("FailedTasksOnly", "Failed tasks only")]} onChange={sel("scope")} ariaLabel="Report scope" /></FormField></>}
        <FormField label="Permissions - IAM role ARN" description="Validated by ARN shape and account only."><Input value={f.role} onChange={set("role")} ariaLabel="IAM role ARN" /></FormField>
      </SpaceBetween></CapabilityContainer> },
    { title: "Review",
      content: <CapabilityContainer id="s3.account.batch-operations" title="Review"><KeyValue items={[
        ["Manifest", `s3://${f.mBucket}/${f.mKey}`], ["Operation", op.label], ["Priority", f.priority], ["Confirmation required", f.confirm ? "Yes" : "No"],
        ["Completion report", f.reportOn ? `s3://${f.rBucket}/${f.rPrefix} (${f.scope})` : "Disabled"], ["IAM role", f.role]]} /></CapabilityContainer> },
  ];
  const disabledNext = (step === 0 && !manifestOk) || (step === 1 && !opOk) || (step === 2 && f.reportOn && !f.rBucket);
  return (
    <Wizard activeStepIndex={step} onNavigate={({ detail }) => { if (!(detail.requestedStepIndex > step && disabledNext)) setStep(detail.requestedStepIndex); }}
      onCancel={onCancel} onSubmit={submit} isLoadingNextStep={busy} steps={steps}
      i18nStrings={{ stepNumberLabel: (n) => `Step ${n}`, collapsedStepsLabel: (n, t) => `Step ${n} of ${t}`, cancelButton: "Cancel", previousButton: "Previous", nextButton: "Next", submitButton: "Create job" }} />
  );
}

export function BatchOperations() {
  const notify = useNotify();
  const jobs = useAsync(() => sw.listJobs(), []);
  const [sel, setSel] = useState([]);
  const [wizard, setWizard] = useState(false);
  const rows = jobs.data || [];
  const id = sel[0]?.id;
  const live = rows.find((j) => j.id === id) || sel[0];
  const det = useAsync(async () => (id ? sw.describeJob(id) : null), [id, live?.status, live?.ok, live?.failed]);
  const cur = live ? { ...live, ...(det.data && det.data.id === live.id ? det.data : {}) } : live;
  const reports = useAsync(async () => (cur && sw.JOB_TERMINAL.includes(cur.status) ? sw.listJobReportKeys(cur) : []), [id, cur?.status]);
  // jobs advance as they are polled: refresh every 2s while anything is not finished
  const pending = rows.some((j) => !sw.JOB_TERMINAL.includes(j.status) && j.status !== "Suspended");
  useEffect(() => {
    if (!pending) return undefined;
    const t = setInterval(() => jobs.reload(), 2000);
    return () => clearInterval(t);
  }, [pending]);   // eslint-disable-line react-hooks/exhaustive-deps
  const act = async (fn, ok) => { try { await fn(); notify.success(ok); jobs.reload(); } catch (e) { notify.error(e); } };
  if (wizard) return <NewJobWizard onCancel={() => setWizard(false)} onDone={() => { setWizard(false); jobs.reload(); }} />;
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="s3.account.batch-operations" title="Batch Operations jobs" counter={`(${rows.length})`}
        description="Run an operation on every object in a manifest. Jobs advance as this page polls them."
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={() => jobs.reload()} />
          <Button disabled={!cur || cur.status !== "Suspended"} onClick={() => act(() => sw.updateJobStatus(cur.id, "Ready"), "Job confirmed - it will run now.")}>Confirm and run</Button>
          <Button disabled={!cur || sw.JOB_TERMINAL.includes(cur.status)} onClick={() => act(() => sw.updateJobStatus(cur.id, "Cancelled", "Cancelled from the console"), "Job cancelled.")}>Cancel job</Button>
          <Button variant="primary" onClick={() => setWizard(true)}>Create job</Button>
        </SpaceBetween>}>
        {jobs.loading && !jobs.data ? <Loading /> : jobs.error ? <ErrorAlert error={jobs.error} />
          : <Table variant="embedded" items={rows} trackBy="id" selectionType="single" selectedItems={cur ? [cur] : []} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
              columnDefinitions={[
                { id: "id", header: "Job ID", cell: (j) => j.id },
                { id: "s", header: "Status", cell: (j) => <StatusIndicator type={statusType(j.status)}>{j.status}</StatusIndicator> },
                { id: "o", header: "Operation", cell: (j) => j.operation },
                { id: "p", header: "Priority", cell: (j) => j.priority },
                { id: "t", header: "Total / succeeded / failed", cell: (j) => `${j.total} / ${j.ok} / ${j.failed}` },
                { id: "c", header: "Created", cell: (j) => fmtDate(j.created) },
                { id: "d", header: "Description", cell: (j) => j.description },
              ]}
              empty={<Box textAlign="center" color="inherit"><b>No jobs</b><Box variant="p" color="inherit">Create a job to run an operation over a manifest of objects.</Box></Box>} />}
      </CapabilityContainer>
      {cur && (
        <CapabilityContainer id="s3.account.batch-operations" title={`Job ${cur.id}`}>
          <SpaceBetween size="m">
            <div data-testid="job-detail"><KeyValue items={[
              ["Status", cur.status + (cur.cause ? ` - ${cur.cause}` : "")], ["Operation", cur.operation], ["Priority", cur.priority],
              ["Progress", `${cur.ok} succeeded, ${cur.failed} failed of ${cur.total} tasks`],
              ["Manifest", cur.manifest ? `${cur.manifest.arn} (${cur.manifest.format})` : ""], ["IAM role", cur.role],
              ["Completion report", cur.report?.enabled ? `s3://${cur.report.bucket}/${cur.report.prefix} (${cur.report.scope})` : "Disabled"],
              ["Status update reason", cur.reason || "-"], ["Termination date", cur.terminated ? fmtDate(cur.terminated) : "-"]]} /></div>
            {cur.failures.length > 0 && <ErrorAlert error={new Error(cur.failures.join("; "))} />}
            {cur.report?.enabled && (
              <Table variant="embedded" header={<Box variant="h3">Completion report objects</Box>} items={reports.data || []} trackBy="key"
                columnDefinitions={[{ id: "k", header: "Object", cell: (r) => `s3://${r.bucket}/${r.key}` }, { id: "z", header: "Size", cell: (r) => `${r.size} B` },
                  { id: "l", header: "", cell: (r) => <a href={`#/s3/buckets/${r.bucket}`}>Open bucket</a> }]}
                empty={<Box textAlign="center" color="inherit">{sw.JOB_TERMINAL.includes(cur.status) ? "No report objects" : "Report is written when the job finishes."}</Box>} />
            )}
          </SpaceBetween>
        </CapabilityContainer>
      )}
    </SpaceBetween>
  );
}
