/* Bucket → Permissions tab. Every section reads live state over the native S3 API and
 * every editable setting writes it back the same way; badges come from the capability
 * registry (core/capabilities/aws/s3.json), never from hand-written text. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import FormField from "@cloudscape-design/components/form-field";
import Modal from "@cloudscape-design/components/modal";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import Tiles from "@cloudscape-design/components/tiles";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Alert from "@cloudscape-design/components/alert";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const BPA = [
  ["BlockPublicAcls", "Block public access to buckets and objects granted through new access control lists (ACLs)"],
  ["IgnorePublicAcls", "Block public access to buckets and objects granted through any access control lists (ACLs)"],
  ["BlockPublicPolicy", "Block public access to buckets and objects granted through new public bucket or access point policies"],
  ["RestrictPublicBuckets", "Block public and cross-account access to buckets and objects through any public bucket or access point policies"],
];
const OWNERSHIP = [
  { value: "BucketOwnerEnforced", label: "ACLs disabled (recommended)", description: "All objects in this bucket are owned by this account. Access is specified using only policies." },
  { value: "BucketOwnerPreferred", label: "ACLs enabled — Bucket owner preferred", description: "New objects written with the bucket-owner-full-control canned ACL are owned by the bucket owner." },
  { value: "ObjectWriter", label: "ACLs enabled — Object writer", description: "The account that uploads an object owns it and controls access through ACLs." },
];
const on = (v) => (v ? "On" : "Off");
const pretty = (s) => { try { return JSON.stringify(JSON.parse(s), null, 2); } catch { return s; } };
const isPublicPolicy = (p) => { try { return JSON.parse(p).Statement?.some((s) => s.Effect === "Allow" && (s.Principal === "*" || s.Principal?.AWS === "*")); } catch { return false; } };

function Loading({ state, children }) {
  if (state.loading) return <StatusIndicator type="loading">Loading</StatusIndicator>;
  if (state.error) return <ErrorAlert error={state.error} />;
  if (state.data?.error) return <ErrorAlert error={state.data.error} />;
  return children(state.data);
}

/** Small modal editor used by every editable section. */
function Editor({ visible, title, onDismiss, onSave, children, saving, error }) {
  return (
    <Modal visible={visible} onDismiss={onDismiss} header={title} size="large"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={saving} onClick={onSave}>Save changes</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="m">{children}{error && <Alert type="error" header={error.code}>{error.message}</Alert>}</SpaceBetween>
    </Modal>
  );
}

function useSaver(capId, reload) {
  const notify = useNotify();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const save = async (fn, what, close) => {
    setSaving(true); setError(null);
    try { await fn(); notify.success(`Successfully edited ${what}.${saveNotice(capId)}`); close(); reload(); }
    catch (e) { setError(e); }
    finally { setSaving(false); }
  };
  return { saving, error, save, reset: () => setError(null) };
}

export default function Permissions({ bucket }) {
  const pab = useAsync(() => api.getPublicAccessBlock(bucket), [bucket]);
  const pol = useAsync(() => api.getPolicy(bucket), [bucket]);
  const own = useAsync(() => api.getOwnership(bucket), [bucket]);
  const acl = useAsync(() => api.getAcl(bucket), [bucket]);
  const cors = useAsync(() => api.getCors(bucket), [bucket]);
  return (
    <SpaceBetween size="l">
      <Overview pab={pab} pol={pol} />
      <PublicAccess bucket={bucket} state={pab} />
      <Policy bucket={bucket} state={pol} />
      <Ownership bucket={bucket} state={own} />
      <CapabilityContainer id="s3.bucket.acl" title="Access control list (ACL)" description="Grant basic read/write permissions to other AWS accounts.">
        <Loading state={acl}>{(d) => (
          <Table variant="embedded" items={d.grants || []}
            columnDefinitions={[{ id: "g", header: "Grantee", cell: (g) => g.grantee }, { id: "t", header: "Type", cell: (g) => g.type }, { id: "p", header: "Permission", cell: (g) => g.permission }]}
            empty={<Box textAlign="center">No grants</Box>} />
        )}</Loading>
      </CapabilityContainer>
      <Cors bucket={bucket} state={cors} />
    </SpaceBetween>
  );
}

function Overview({ pab, pol }) {
  // Derived from the live Block Public Access + policy state — not a canned value.
  const ready = !pab.loading && !pol.loading;
  const c = pab.data?.config;
  const allBlocked = c && Object.values(c).every(Boolean);
  const access = !ready ? null : allBlocked ? "Bucket and objects not public" : isPublicPolicy(pol.data?.policy) ? "Public" : "Objects can be public";
  return (
    <CapabilityContainer id="s3.bucket.public-access-block" title="Permissions overview">
      <Box variant="awsui-key-label">Access</Box>
      {access ? <StatusIndicator type={access === "Public" ? "warning" : allBlocked ? "success" : "info"}>{access}</StatusIndicator> : <StatusIndicator type="loading">Loading</StatusIndicator>}
    </CapabilityContainer>
  );
}

function PublicAccess({ bucket, state }) {
  const [edit, setEdit] = useState(null);
  const s = useSaver("s3.bucket.public-access-block", state.reload);
  const cur = state.data?.config || Object.fromEntries(BPA.map(([k]) => [k, false]));
  const all = Object.values(cur).every(Boolean);
  return (
    <CapabilityContainer id="s3.bucket.public-access-block" title="Block public access (bucket settings)"
      description="Public access is granted to buckets and objects through access control lists (ACLs), bucket policies, access point policies, or all."
      actions={<Button onClick={() => { s.reset(); setEdit({ ...cur }); }}>Edit</Button>}>
      <Loading state={state}>{() => (
        <SpaceBetween size="s">
          <div><Box variant="awsui-key-label">Block all public access</Box><StatusIndicator type={all ? "success" : "warning"}>{on(all)}</StatusIndicator></div>
          <ColumnLayout columns={2} variant="text-grid">
            {BPA.map(([k, label]) => <div key={k}><Box variant="small">{label}</Box><div>{on(cur[k])}</div></div>)}
          </ColumnLayout>
        </SpaceBetween>
      )}</Loading>
      <Editor visible={!!edit} title="Edit Block public access (bucket settings)" onDismiss={() => setEdit(null)} saving={s.saving} error={s.error}
        onSave={() => s.save(() => api.putPublicAccessBlock(bucket, edit), "Block public access (bucket settings)", () => setEdit(null))}>
        {edit && <>
          <Checkbox checked={Object.values(edit).every(Boolean)} onChange={({ detail }) => setEdit(Object.fromEntries(BPA.map(([k]) => [k, detail.checked])))}><b>Block all public access</b></Checkbox>
          <Box padding={{ left: "l" }}><SpaceBetween size="xs">
            {BPA.map(([k, label]) => <Checkbox key={k} checked={edit[k]} onChange={({ detail }) => setEdit({ ...edit, [k]: detail.checked })}>{label}</Checkbox>)}
          </SpaceBetween></Box>
        </>}
      </Editor>
    </CapabilityContainer>
  );
}

function Policy({ bucket, state }) {
  const [edit, setEdit] = useState(null);
  const [jsonErr, setJsonErr] = useState(null);
  const s = useSaver("s3.bucket.policy", state.reload);
  const notify = useNotify();
  const has = !!state.data?.policy;
  return (
    <CapabilityContainer id="s3.bucket.policy" title="Bucket policy"
      description="The bucket policy, written in JSON, provides access to the objects stored in the bucket."
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={!has} onClick={async () => { try { await api.deletePolicy(bucket); notify.success("Successfully deleted bucket policy."); state.reload(); } catch (e) { notify.error(e); } }}>Delete</Button>
        <Button onClick={() => { s.reset(); setJsonErr(null); setEdit(has ? pretty(state.data.policy) : JSON.stringify({ Version: "2012-10-17", Statement: [] }, null, 2)); }}>Edit</Button>
      </SpaceBetween>}>
      <Loading state={state}>{(d) => d.policy
        ? <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{pretty(d.policy)}</pre></Box>
        : <Box color="text-body-secondary">No policy to display.</Box>}</Loading>
      <Editor visible={edit !== null} title="Edit bucket policy" onDismiss={() => setEdit(null)} saving={s.saving} error={s.error}
        onSave={() => {
          try { JSON.parse(edit); } catch (e) { setJsonErr(`Policy is not valid JSON: ${e.message}`); return; }
          setJsonErr(null);
          s.save(() => api.putPolicy(bucket, edit), "bucket policy", () => setEdit(null));
        }}>
        <FormField label="Policy" errorText={jsonErr} stretch>
          <Textarea rows={18} value={edit || ""} onChange={({ detail }) => setEdit(detail.value)} spellcheck={false} />
        </FormField>
      </Editor>
    </CapabilityContainer>
  );
}

function Ownership({ bucket, state }) {
  const [edit, setEdit] = useState(null);
  const s = useSaver("s3.bucket.ownership", state.reload);
  const cur = state.data?.ownership;
  const label = OWNERSHIP.find((o) => o.value === cur)?.label;
  return (
    <CapabilityContainer id="s3.bucket.ownership" title="Object Ownership"
      description="Control ownership of objects written to this bucket from other AWS accounts and the use of access control lists (ACLs)."
      actions={<Button onClick={() => { s.reset(); setEdit(cur || "BucketOwnerEnforced"); }}>Edit</Button>}>
      <Loading state={state}>{() => (
        <div><Box variant="awsui-key-label">Object Ownership</Box><div>{cur ? `${cur}${label ? ` — ${label}` : ""}` : "Not configured"}</div></div>
      )}</Loading>
      <Editor visible={!!edit} title="Edit Object Ownership" onDismiss={() => setEdit(null)} saving={s.saving} error={s.error}
        onSave={() => s.save(() => api.putOwnership(bucket, edit), "Object Ownership", () => setEdit(null))}>
        <Tiles value={edit} onChange={({ detail }) => setEdit(detail.value)} items={OWNERSHIP} columns={1} />
      </Editor>
    </CapabilityContainer>
  );
}

function Cors({ bucket, state }) {
  const [edit, setEdit] = useState(null);
  const [jsonErr, setJsonErr] = useState(null);
  const s = useSaver("s3.bucket.cors", state.reload);
  const rules = state.data?.rules;
  return (
    <CapabilityContainer id="s3.bucket.cors" title="Cross-origin resource sharing (CORS)"
      description="The CORS configuration, written in JSON, defines a way for client web applications that are loaded in one domain to interact with resources in a different domain."
      actions={<Button onClick={() => { s.reset(); setJsonErr(null); setEdit(JSON.stringify(rules || [], null, 2)); }}>Edit</Button>}>
      <Loading state={state}>{() => rules?.length
        ? <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(rules, null, 2)}</pre></Box>
        : <Box color="text-body-secondary">No configurations to display.</Box>}</Loading>
      <Editor visible={edit !== null} title="Edit cross-origin resource sharing (CORS)" onDismiss={() => setEdit(null)} saving={s.saving} error={s.error}
        onSave={() => {
          let parsed;
          try { parsed = JSON.parse(edit); if (!Array.isArray(parsed)) throw new Error("expected a JSON array of rules"); }
          catch (e) { setJsonErr(`CORS configuration is not valid: ${e.message}`); return; }
          setJsonErr(null);
          s.save(() => api.putCors(bucket, parsed), "cross-origin resource sharing (CORS)", () => setEdit(null));
        }}>
        <FormField label="Cross-origin resource sharing (CORS)" description='JSON array, e.g. [{"AllowedMethods":["GET"],"AllowedOrigins":["*"]}]' errorText={jsonErr} stretch>
          <Textarea rows={16} value={edit || ""} onChange={({ detail }) => setEdit(detail.value)} spellcheck={false} />
        </FormField>
      </Editor>
    </CapabilityContainer>
  );
}
