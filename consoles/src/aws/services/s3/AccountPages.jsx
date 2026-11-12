/* S3 account-level pages backed by the shared core: Block Public Access for this account,
 * directory buckets (S3 Express One Zone) and Object Lambda Access Points. Each is a
 * CapabilityContainer (registry ids s3.account.*), so its limits show as the capability badge. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtBytes, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";
import * as sw from "./sweepApi.js";

const PAB_LABEL = {
  BlockPublicAcls: ["Block public access to buckets and objects granted through new access control lists (ACLs)", "Rejects PUT requests that grant public access through ACLs."],
  IgnorePublicAcls: ["Block public access to buckets and objects granted through any access control lists (ACLs)", "Ignores all ACLs that grant public access."],
  BlockPublicPolicy: ["Block public access to buckets and objects granted through new public bucket or access point policies", "Rejects new bucket and access point policies that grant public access."],
  RestrictPublicBuckets: ["Block public and cross-account access to buckets and objects through any public bucket or access point policies", "Ignores public and cross-account access for buckets with public policies."],
};

export function AccountPublicAccessBlock() {
  const notify = useNotify();
  const pab = useAsync(() => sw.getAccountPab(), []);
  const [edit, setEdit] = useState(null);
  const [typed, setTyped] = useState("");
  const [saving, setSaving] = useState(false);
  const cur = pab.data || Object.fromEntries(sw.ACCOUNT_PAB_KEYS.map((k) => [k, false]));
  const all = (c) => sw.ACCOUNT_PAB_KEYS.every((k) => c[k]);
  const save = async () => {
    setSaving(true);
    try {
      await sw.putAccountPab(edit);
      notify.success(`Successfully edited account settings for Block Public Access.${saveNotice("s3.account.account-public-access-block")}`);
      setEdit(null); setTyped(""); pab.reload();
    } catch (e) { notify.error(e); } finally { setSaving(false); }
  };
  return (
    <CapabilityContainer id="s3.account.account-public-access-block" title="Block Public Access settings for this account"
      description="Public access is granted to buckets and objects through ACLs, access point policies, bucket policies, or all. These settings apply to every bucket in this account."
      actions={<Button onClick={() => { setEdit({ ...cur }); setTyped(""); }}>Edit</Button>}>
      {pab.loading ? <StatusIndicator type="loading">Loading</StatusIndicator> : pab.error ? <ErrorAlert error={pab.error} />
        : <SpaceBetween size="s">
          <div data-testid="account-pab-summary"><StatusIndicator type={all(cur) ? "success" : "warning"}>{all(cur) ? "Block all public access: On" : pab.data ? "Block all public access: Off (some settings on)" : "Block all public access: Off"}</StatusIndicator></div>
          <Table variant="embedded" items={sw.ACCOUNT_PAB_KEYS.map((k) => ({ key: k, on: cur[k] }))} trackBy="key"
            columnDefinitions={[
              { id: "s", header: "Setting", cell: (i) => PAB_LABEL[i.key][0] },
              { id: "v", header: "Value", cell: (i) => <StatusIndicator type={i.on ? "success" : "stopped"}>{i.on ? "On" : "Off"}</StatusIndicator> },
            ]} />
        </SpaceBetween>}
      <Modal visible={!!edit} onDismiss={() => setEdit(null)} header="Edit Block Public Access settings for this account"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} disabled={typed !== "confirm"} onClick={save}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <SpaceBetween size="m">
          <Checkbox checked={all(edit)} onChange={({ detail }) => setEdit(Object.fromEntries(sw.ACCOUNT_PAB_KEYS.map((k) => [k, detail.checked])))}><b>Block all public access</b></Checkbox>
          {sw.ACCOUNT_PAB_KEYS.map((k) => (
            <Checkbox key={k} checked={edit[k]} description={PAB_LABEL[k][1]} onChange={({ detail }) => setEdit({ ...edit, [k]: detail.checked })}>{PAB_LABEL[k][0]}</Checkbox>
          ))}
          <FormField label="To confirm these settings, type confirm in the field."><Input value={typed} placeholder="confirm" onChange={({ detail }) => setTyped(detail.value)} ariaLabel="Confirm" /></FormField>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}

const ZONES = ["use1-az4", "use1-az5", "use1-az6", "use2-az1", "usw2-az1", "usw2-az3", "usw2-az4", "euw1-az1", "euw1-az3", "aps1-az1", "apne1-az4"];

export function DirectoryBuckets() {
  const notify = useNotify();
  const list = useAsync(() => sw.listDirectoryBuckets(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState(null);   // {kind: "empty"|"delete"}
  const [objForm, setObjForm] = useState(null);
  const rows = list.data || [];
  const bucket = sel[0]?.name;
  const objs = useAsync(async () => (bucket ? await sw.listBucketObjectsFlat(bucket) : []), [bucket]);
  const reloadAll = () => { list.reload(); objs.reload(); };
  const run = async (fn, ok) => { try { await fn(); notify.success(ok); } catch (e) { notify.error(e); } };
  const fullName = create ? sw.directoryBucketName(create.base, create.zone) : "";
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="s3.account.directory-buckets" title="Directory buckets" counter={`(${rows.length})`}
        description="Directory buckets use the S3 Express One Zone storage class for single-zone, low-latency workloads."
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={() => list.reload()} />
          <Button disabled={sel.length !== 1} onClick={() => setConfirm({ kind: "empty" })}>Empty</Button>
          <Button disabled={sel.length !== 1} onClick={() => setConfirm({ kind: "delete" })}>Delete</Button>
          <Button variant="primary" onClick={() => setCreate({ base: "", zone: ZONES[4] })}>Create bucket</Button>
        </SpaceBetween>}>
        {list.loading ? <StatusIndicator type="loading">Loading</StatusIndicator> : list.error ? <ErrorAlert error={list.error} />
          : <Table variant="embedded" items={rows} trackBy="name" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
              columnDefinitions={[
                { id: "n", header: "Name", cell: (b) => b.name },
                { id: "r", header: "AWS Region", cell: (b) => b.region },
                { id: "c", header: "Creation date", cell: (b) => fmtDate(b.created) },
              ]}
              empty={<Box textAlign="center" color="inherit"><b>No directory buckets</b><Box variant="p" color="inherit">You don't have any directory buckets.</Box></Box>} />}
      </CapabilityContainer>
      {bucket && (
        <CapabilityContainer id="s3.account.directory-buckets" title={`Objects in ${bucket}`} counter={`(${(objs.data || []).length})`}
          actions={<Button onClick={() => setObjForm({ key: "", body: "" })}>Create object</Button>}>
          {objs.loading ? <StatusIndicator type="loading">Loading</StatusIndicator> : objs.error ? <ErrorAlert error={objs.error} />
            : <Table variant="embedded" items={objs.data || []} trackBy="key"
                columnDefinitions={[
                  { id: "k", header: "Name", cell: (o) => o.key },
                  { id: "s", header: "Size", cell: (o) => fmtBytes(o.size) },
                  { id: "sc", header: "Storage class", cell: (o) => o.storageClass },
                  { id: "a", header: "", cell: (o) => <Button variant="inline-link" onClick={() => run(async () => { await api.deleteObject(bucket, o.key); objs.reload(); }, `Deleted ${o.key}.`)}>Delete</Button> },
                ]}
                empty={<Box textAlign="center" color="inherit"><b>No objects</b></Box>} />}
        </CapabilityContainer>
      )}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create directory bucket"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} disabled={!create?.base} onClick={async () => {
            setSaving(true);
            try { await sw.createDirectoryBucket(fullName, create.zone); notify.success(`Successfully created directory bucket "${fullName}".${saveNotice("s3.account.directory-buckets")}`); setCreate(null); list.reload(); }
            catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create bucket</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Availability Zone" description="Directory buckets live in a single Availability Zone.">
            <Select selectedOption={{ value: create.zone, label: create.zone }} options={ZONES.map((z) => ({ value: z, label: z }))} onChange={({ detail }) => setCreate({ ...create, zone: detail.selectedOption.value })} ariaLabel="Availability Zone" />
          </FormField>
          <FormField label="Bucket name" description={`Name: ${fullName || "<base>--<zone>--x-s3"}`}><Input value={create.base} placeholder="my-bucket" onChange={({ detail }) => setCreate({ ...create, base: detail.value })} ariaLabel="Bucket base name" /></FormField>
        </SpaceBetween>}
      </Modal>
      <Modal visible={!!confirm} onDismiss={() => setConfirm(null)} header={confirm?.kind === "empty" ? "Empty directory bucket" : "Delete directory bucket"}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setConfirm(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            const kind = confirm.kind; setConfirm(null);
            await run(async () => {
              for (const key of await api.listAllObjectKeys(bucket)) await api.deleteObject(bucket, key);
              if (kind === "delete") { await api.deleteBucket(bucket); setSel([]); }
              reloadAll();
            }, kind === "empty" ? `Successfully emptied bucket "${bucket}".` : `Successfully deleted directory bucket "${bucket}".`);
          }}>{confirm?.kind === "empty" ? "Empty" : "Delete"}</Button>
        </SpaceBetween></Box>}>
        {confirm?.kind === "empty" ? <>Permanently delete <b>all</b> objects in <b>{bucket}</b>?</> : <>Delete directory bucket <b>{bucket}</b> and every object in it?</>}
      </Modal>
      <Modal visible={!!objForm} onDismiss={() => setObjForm(null)} header="Create object"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setObjForm(null)}>Cancel</Button>
          <Button variant="primary" disabled={!objForm?.key} onClick={async () => { const f = objForm; setObjForm(null); await run(async () => { await api.putObject(bucket, f.key, f.body, "text/plain"); objs.reload(); }, `Uploaded ${f.key}.`); }}>Create object</Button>
        </SpaceBetween></Box>}>
        {objForm && <SpaceBetween size="m">
          <FormField label="Object key"><Input value={objForm.key} onChange={({ detail }) => setObjForm({ ...objForm, key: detail.value })} ariaLabel="Object key" /></FormField>
          <FormField label="Content"><Textarea value={objForm.body} onChange={({ detail }) => setObjForm({ ...objForm, body: detail.value })} ariaLabel="Object content" /></FormField>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}

export function ObjectLambdaAccessPoints() {
  const notify = useNotify();
  const list = useAsync(() => sw.listObjectLambdaAccessPoints(), []);
  const aps = useAsync(() => sw.listAccessPoints(), []);
  const fns = useAsync(() => sw.listLambdaFunctions().catch(() => []), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [saving, setSaving] = useState(false);
  const detail = useAsync(async () => (sel[0] ? sw.getObjectLambdaAccessPoint(sel[0].name) : null), [sel[0]?.name]);
  const rows = list.data || [];
  const apOptions = (aps.data || []).map((a) => ({ value: a.arn, label: a.name, description: a.bucket }));
  const fnOptions = (fns.data || []).map((f) => ({ value: f.arn, label: f.name }));
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="s3.account.object-lambda-access-points" title="Object Lambda Access Points" counter={`(${rows.length})`}
        description="An Object Lambda Access Point transforms GetObject responses with a Lambda function."
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={() => list.reload()} />
          <Button disabled={sel.length !== 1} onClick={async () => { try { await sw.deleteObjectLambdaAccessPoint(sel[0].name); notify.success("Successfully deleted Object Lambda Access Point."); setSel([]); list.reload(); } catch (e) { notify.error(e); } }}>Delete</Button>
          <Button variant="primary" onClick={() => { aps.reload(); fns.reload(); setCreate({ name: "", supporting: "", functionArn: "", payload: "", range: false }); }}>Create Object Lambda Access Point</Button>
        </SpaceBetween>}>
        {list.loading ? <StatusIndicator type="loading">Loading</StatusIndicator> : list.error ? <ErrorAlert error={list.error} />
          : <Table variant="embedded" items={rows} trackBy="name" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
              columnDefinitions={[
                { id: "n", header: "Name", cell: (a) => a.name },
                { id: "al", header: "Object Lambda Access Point alias", cell: (a) => a.alias },
                { id: "arn", header: "Object Lambda Access Point ARN", cell: (a) => a.arn },
              ]}
              empty={<Box textAlign="center" color="inherit"><b>No Object Lambda Access Points</b><Box variant="p" color="inherit">Create one on top of an existing access point.</Box></Box>} />}
      </CapabilityContainer>
      {sel[0] && detail.data && (
        <CapabilityContainer id="s3.account.object-lambda-access-points" title={`Configuration - ${sel[0].name}`}>
          <SpaceBetween size="xs">
            <div>Supporting access point: <b>{detail.data.supporting}</b></div>
            {detail.data.transformations.map((t, i) => <div key={i}>{t.actions.join(", ")} -&gt; Lambda <b>{t.functionArn}</b>{t.payload ? ` (payload: ${t.payload})` : ""}</div>)}
            <div>Allowed features: {detail.data.allowed.join(", ") || "none"}</div>
          </SpaceBetween>
        </CapabilityContainer>
      )}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create Object Lambda Access Point" size="large"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} disabled={!create?.name || !create?.supporting || !create?.functionArn} onClick={async () => {
            setSaving(true);
            try {
              await sw.createObjectLambdaAccessPoint(create.name, { supporting: create.supporting, functionArn: create.functionArn, payload: create.payload, allowed: create.range ? ["GetObject-Range"] : [] });
              notify.success(`Successfully created Object Lambda Access Point ${create.name}.${saveNotice("s3.account.object-lambda-access-points")}`);
              setCreate(null); list.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create Object Lambda Access Point</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Object Lambda Access Point name" description="3-45 characters: lowercase letters, numbers and hyphens."><Input value={create.name} onChange={({ detail }) => setCreate({ ...create, name: detail.value })} ariaLabel="Object Lambda Access Point name" /></FormField>
          <FormField label="Supporting Access Point" description="The standard access point that serves the original object.">
            <Select selectedOption={apOptions.find((o) => o.value === create.supporting) || null} options={apOptions} placeholder="Choose an access point" empty="No access points - create one first" onChange={({ detail }) => setCreate({ ...create, supporting: detail.selectedOption.value })} ariaLabel="Supporting access point" />
          </FormField>
          <FormField label="Lambda function" description="Invoked for every GetObject through this access point.">
            <Select selectedOption={fnOptions.find((o) => o.value === create.functionArn) || null} options={fnOptions} placeholder="Choose a Lambda function" empty="No Lambda functions" onChange={({ detail }) => setCreate({ ...create, functionArn: detail.selectedOption.value })} ariaLabel="Lambda function" />
          </FormField>
          <FormField label="Payload (optional)" description="Passed to the function as configuration.payload."><Input value={create.payload} onChange={({ detail }) => setCreate({ ...create, payload: detail.value })} ariaLabel="Payload" /></FormField>
          <Checkbox checked={create.range} onChange={({ detail }) => setCreate({ ...create, range: detail.checked })}>Allow GetObject range requests (GetObject-Range)</Checkbox>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}
