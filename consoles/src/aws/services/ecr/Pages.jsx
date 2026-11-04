/* Amazon ECR console: repositories, repository detail (images, scan findings, lifecycle policy editor + preview, permissions,
 * settings) and the private-registry settings (replication, scanning, registry policy). Every control is a real ECR API call. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate, useRoute } from "../../../common/router.js";
import * as api from "./api.js";

const MUT = [{ value: "MUTABLE", label: "Mutable" }, { value: "IMMUTABLE", label: "Immutable" }];
const SAMPLE_LIFECYCLE = JSON.stringify({ rules: [{ rulePriority: 1, description: "Expire untagged images after 14 days", selection: { tagStatus: "untagged", countType: "sinceImagePushed", countUnit: "days", countNumber: 14 }, action: { type: "expire" } }] }, null, 2);
const sevType = (s) => ({ CRITICAL: "error", HIGH: "error", MEDIUM: "warning", LOW: "info" }[s] || "stopped");
const pretty = (t) => { try { return JSON.stringify(JSON.parse(t), null, 2); } catch { return t || ""; } };

/* ── Repositories ──────────────────────────────────────────────────────────── */
export function Repositories() {
  const notify = useNotify();
  const t = useAsync(() => api.listRepositories(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const [f, setF] = useState({ name: "", mutability: MUT[0], scan: false });
  const [err, setErr] = useState(null);
  const doCreate = async () => {
    try { await api.createRepository(f.name, { mutability: f.mutability.value, scanOnPush: f.scan }); notify.success(`Successfully created repository ${f.name}.`);
      setCreate(false); setF({ name: "", mutability: MUT[0], scan: false }); t.reload(); } catch (e) { setErr(e); }
  };
  return (
    <>
      <ResourceTable resourceName="Private repositories" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload}
        trackBy="repositoryName" selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Find repositories"
        empty={{ title: "No repositories", description: "Create a repository to store container images." }}
        columns={[
          { id: "n", header: "Repository name", isRowHeader: true, sortingField: "repositoryName", cell: (r) => <Link href={`#/ecr/repositories/view?name=${encodeURIComponent(r.repositoryName)}`} onFollow={follow}>{r.repositoryName}</Link> },
          { id: "u", header: "URI", cell: (r) => r.repositoryUri },
          { id: "c", header: "Created at", sortingField: "createdAt", cell: (r) => fmtDate(r.createdAt) },
          { id: "m", header: "Tag immutability", cell: (r) => (r.imageTagMutability === "IMMUTABLE" ? "Enabled" : "Disabled") },
          { id: "s", header: "Scan on push", cell: (r) => (r.imageScanningConfiguration?.scanOnPush ? "Enabled" : "Disabled") },
          { id: "e", header: "Encryption", cell: (r) => r.encryptionConfiguration?.encryptionType },
        ]}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
          <Button variant="primary" onClick={() => { setErr(null); setCreate(true); }}>Create repository</Button>
        </SpaceBetween>} />
      <Modal visible={create} onDismiss={() => setCreate(false)} header="Create private repository"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setCreate(false)}>Cancel</Button>
          <Button variant="primary" onClick={doCreate}>Create repository</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m"><ErrorAlert error={err} />
          <FormField label="Repository name" description="Lowercase letters, digits and . _ - / separators (2-256 characters).">
            <Input ariaLabel="Repository name" value={f.name} onChange={({ detail }) => setF({ ...f, name: detail.value })} placeholder="my-app/web" /></FormField>
          <FormField label="Tag immutability"><Select selectedOption={f.mutability} options={MUT} onChange={({ detail }) => setF({ ...f, mutability: detail.selectedOption })} /></FormField>
          <Checkbox checked={f.scan} onChange={({ detail }) => setF({ ...f, scan: detail.checked })}>Scan on push</Checkbox>
        </SpaceBetween>
      </Modal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="repository" names={sel.map((r) => r.repositoryName)}
        onConfirm={async () => { await api.deleteRepository(sel[0].repositoryName, true); notify.success("Deleted repository (and its images)."); setSel([]); t.reload(); }} />
    </>
  );
}

/* ── Repository detail ─────────────────────────────────────────────────────── */
function Images({ name, repo }) {
  const notify = useNotify();
  const t = useAsync(() => api.listImages(name), [name]);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const scan = async () => { try { await api.startScan(name, sel[0].imageDigest); notify.success("Image scan complete."); t.reload(); } catch (e) { notify.error(e.message); } };
  return (
    <>
      <ResourceTable resourceName="Images" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="imageDigest"
        selectionType="multi" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Find images" empty={{ title: "No images", description: `Push an image to ${repo.repositoryUri}.` }}
        columns={[
          { id: "t", header: "Image tags", isRowHeader: true, cell: (i) => (i.imageTags || []).join(", ") || <Box color="text-status-inactive">Untagged</Box> },
          { id: "d", header: "Digest", cell: (i) => <span title={i.imageDigest}>{i.imageDigest.slice(0, 19)}…</span> },
          { id: "z", header: "Size", sortingField: "imageSizeInBytes", cell: (i) => fmtBytes(i.imageSizeInBytes) },
          { id: "p", header: "Pushed at", sortingField: "imagePushedAt", cell: (i) => fmtDate(i.imagePushedAt) },
          { id: "s", header: "Scan status", cell: (i) => i.imageScanStatus ? <StatusIndicator type={i.imageScanStatus.status === "COMPLETE" ? "success" : "in-progress"}>{i.imageScanStatus.status}</StatusIndicator> : "-" },
          { id: "v", header: "Vulnerabilities", cell: (i) => { const c = i.imageScanFindingsSummary?.findingSeverityCounts; return c ? (Object.entries(c).map(([k, v]) => `${k}: ${v}`).join(", ") || "None") : "-"; } },
        ]}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button disabled={sel.length !== 1} onClick={scan}>Scan</Button>
          <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        </SpaceBetween>} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="image" names={sel.map((i) => (i.imageTags?.[0] || i.imageDigest.slice(0, 19)))}
        onConfirm={async () => { await api.deleteImages(name, sel.map((i) => i.imageDigest)); notify.success("Deleted images."); setSel([]); t.reload(); }} />
    </>
  );
}

function Findings({ name }) {
  const imgs = useAsync(() => api.listImages(name), [name]);
  const [pick, setPick] = useState(null);
  const f = useAsync(() => (pick ? api.scanFindings(name, pick.value) : Promise.resolve(undefined)), [pick?.value]);
  const scanned = (imgs.data || []).filter((i) => i.imageScanStatus);
  const opts = (imgs.data || []).map((i) => ({ value: i.imageDigest, label: (i.imageTags?.[0] || "untagged") + " · " + i.imageDigest.slice(7, 19), description: i.imageScanStatus ? "Scanned" : "Not scanned" }));
  const fi = f.data?.imageScanFindings;
  const rows = fi ? (fi.findings || fi.enhancedFindings || []).map((x) => ({ id: x.name || x.findingArn || x.title, sev: x.severity, pkg: x.packageVulnerabilityDetails?.vulnerablePackages?.[0]?.name || (x.attributes || []).find((a) => a.key === "package_name")?.value || "-", desc: x.description || x.title || "-", uri: x.uri || x.packageVulnerabilityDetails?.sourceUrl })) : [];
  return (
    <SpaceBetween size="m">
      <Container header={<Header variant="h2" description={`${scanned.length} of ${(imgs.data || []).length} images scanned`}>Scan findings</Header>}>
        <FormField label="Image"><Select ariaLabel="Image" selectedOption={pick} options={opts} onChange={({ detail }) => setPick(detail.selectedOption)} placeholder="Choose an image" /></FormField>
      </Container>
      {pick && f.data === null && <Box color="text-status-inactive">This image has not been scanned yet. Select it on the Images tab and choose Scan.</Box>}
      {fi && <>
        <KeyValue title="Summary" columns={4} items={[["Scan completed", fmtDate(fi.imageScanCompletedAt)], ["Engine", fi.engine || "-"], ...Object.entries(fi.findingSeverityCounts || {})]} />
        <ResourceTable resourceName="Vulnerabilities" items={rows} trackBy="id" filterPlaceholder="Find findings" empty={{ title: "No vulnerabilities found" }}
          columns={[
            { id: "n", header: "Name", isRowHeader: true, cell: (r) => (r.uri ? <Link external href={r.uri}>{r.id}</Link> : r.id) },
            { id: "s", header: "Severity", sortingField: "sev", cell: (r) => <StatusIndicator type={sevType(r.sev)}>{r.sev}</StatusIndicator> },
            { id: "p", header: "Package", cell: (r) => r.pkg },
            { id: "d", header: "Description", cell: (r) => r.desc }]} />
      </>}
    </SpaceBetween>
  );
}

function Lifecycle({ name }) {
  const notify = useNotify();
  const cur = useAsync(() => api.getLifecycle(name), [name]);
  const prev = useAsync(() => api.getPreview(name), [name]);
  const [text, setText] = useState(null);
  const [err, setErr] = useState(null);
  const value = text ?? (cur.data ? pretty(cur.data.lifecyclePolicyText) : "");
  const save = async () => { try { setErr(null); await api.putLifecycle(name, value); notify.success("Lifecycle policy saved."); setText(null); cur.reload(); } catch (e) { setErr(e); } };
  const preview = async () => { try { setErr(null); await api.startPreview(name, value); prev.reload(); notify.success("Lifecycle preview ready."); } catch (e) { setErr(e); } };
  const remove = async () => { try { await api.deleteLifecycle(name); notify.success("Lifecycle policy deleted."); setText(null); cur.reload(); } catch (e) { setErr(e); } };
  const results = prev.data?.previewResults || [];
  return (
    <SpaceBetween size="m">
      <Container header={<Header variant="h2" description="Rules expire images by age or count. Evaluated against the repository's real images." actions={<SpaceBetween direction="horizontal" size="xs">
        <Button onClick={() => setText(SAMPLE_LIFECYCLE)}>Insert example</Button><Button disabled={!cur.data} onClick={remove}>Delete</Button>
        <Button onClick={preview} disabled={!value.trim()}>Dry run</Button><Button variant="primary" onClick={save} disabled={!value.trim()}>Save</Button></SpaceBetween>}>Lifecycle policy</Header>}>
        <SpaceBetween size="s"><ErrorAlert error={err} />
          <Textarea ariaLabel="Lifecycle policy JSON" rows={14} value={value} onChange={({ detail }) => setText(detail.value)} spellcheck={false} /></SpaceBetween>
      </Container>
      {prev.data && <ResourceTable resourceName="Dry run results" items={results} trackBy="imageDigest" empty={{ title: "No images would expire" }}
        columns={[{ id: "t", header: "Image tags", isRowHeader: true, cell: (r) => (r.imageTags || []).join(", ") || "Untagged" },
          { id: "d", header: "Digest", cell: (r) => r.imageDigest.slice(0, 19) + "…" }, { id: "p", header: "Pushed at", cell: (r) => fmtDate(r.imagePushedAt) },
          { id: "r", header: "Rule priority", cell: (r) => r.appliedRulePriority }, { id: "a", header: "Action", cell: (r) => r.action.type }]} />}
    </SpaceBetween>
  );
}

function PolicyEditor({ title, description, load, save, remove, example }) {
  const notify = useNotify();
  const cur = useAsync(load, []);
  const [text, setText] = useState(null);
  const [err, setErr] = useState(null);
  const value = text ?? (cur.data ? pretty(cur.data.policyText) : "");
  const go = async () => { try { setErr(null); await save(value); notify.success(`${title} saved.`); setText(null); cur.reload(); } catch (e) { setErr(e); } };
  const rm = async () => { try { await remove(); notify.success(`${title} deleted.`); setText(null); cur.reload(); } catch (e) { setErr(e); } };
  return (
    <Container header={<Header variant="h2" description={description} actions={<SpaceBetween direction="horizontal" size="xs">
      <Button onClick={() => setText(JSON.stringify(example, null, 2))}>Insert example</Button><Button disabled={!cur.data} onClick={rm}>Delete</Button>
      <Button variant="primary" disabled={!value.trim()} onClick={go}>Save</Button></SpaceBetween>}>{title}</Header>}>
      <SpaceBetween size="s"><ErrorAlert error={err} /><Textarea ariaLabel={`${title} JSON`} rows={12} value={value} onChange={({ detail }) => setText(detail.value)} spellcheck={false} /></SpaceBetween>
    </Container>
  );
}

function RepoSettings({ repo, reload }) {
  const notify = useNotify();
  const [err, setErr] = useState(null);
  const run = (fn, msg) => async () => { try { setErr(null); await fn(); notify.success(msg); reload(); } catch (e) { setErr(e); } };
  const immutable = repo.imageTagMutability === "IMMUTABLE";
  const scan = !!repo.imageScanningConfiguration?.scanOnPush;
  return (
    <SpaceBetween size="m"><ErrorAlert error={err} />
      <Container header={<Header variant="h2">Tag immutability</Header>}><SpaceBetween size="s">
        <Box>{immutable ? "Image tags cannot be overwritten." : "Image tags can be overwritten by later pushes."}</Box>
        <Button onClick={run(() => api.putTagMutability(repo.repositoryName, immutable ? "MUTABLE" : "IMMUTABLE"), "Tag immutability updated.")}>{immutable ? "Disable tag immutability" : "Enable tag immutability"}</Button></SpaceBetween></Container>
      <Container header={<Header variant="h2">Image scanning</Header>}><SpaceBetween size="s">
        <Box>Scan on push is {scan ? "enabled" : "disabled"}.</Box>
        <Button onClick={run(() => api.putScanOnPush(repo.repositoryName, !scan), "Scan on push updated.")}>{scan ? "Disable scan on push" : "Enable scan on push"}</Button></SpaceBetween></Container>
    </SpaceBetween>
  );
}

export function RepositoryDetail() {
  const { query } = useRoute();
  const name = query.name;
  const r = useAsync(() => api.getRepository(name), [name]);
  if (r.error) return <ErrorAlert error={r.error} />;
  const repo = r.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={() => navigate("ecr", "repositories")}>Back to repositories</Button>}>{name}</Header>}>
      {repo && <SpaceBetween size="l">
        <KeyValue title="Details" columns={3} items={[["Repository URI", repo.repositoryUri], ["ARN", repo.repositoryArn], ["Created at", fmtDate(repo.createdAt)],
          ["Tag immutability", repo.imageTagMutability], ["Scan on push", repo.imageScanningConfiguration?.scanOnPush ? "Enabled" : "Disabled"], ["Encryption", repo.encryptionConfiguration?.encryptionType]]} />
        <Tabs tabs={[
          { id: "images", label: "Images", content: <Images name={name} repo={repo} /> },
          { id: "findings", label: "Scan findings", content: <Findings name={name} /> },
          { id: "lifecycle", label: "Lifecycle policy", content: <Lifecycle name={name} /> },
          { id: "perm", label: "Permissions", content: <PolicyEditor title="Repository policy" description="Resource policy controlling who can pull and push."
            load={() => api.getRepoPolicy(name)} save={(t) => api.setRepoPolicy(name, t)} remove={() => api.deleteRepoPolicy(name)}
            example={{ Version: "2012-10-17", Statement: [{ Sid: "AllowPull", Effect: "Allow", Principal: { AWS: "arn:aws:iam::123456789012:root" }, Action: ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"] }] }} /> },
          { id: "settings", label: "Settings", content: <RepoSettings repo={repo} reload={r.reload} /> },
        ]} />
      </SpaceBetween>}
    </ContentLayout>
  );
}

/* ── Private registry settings ─────────────────────────────────────────────── */
function Replication() {
  const notify = useNotify();
  const reg = useAsync(() => api.describeRegistry(), []);
  const [dlg, setDlg] = useState(false);
  const [f, setF] = useState({ region: "us-west-2", registry: "123456789012", prefix: "" });
  const [err, setErr] = useState(null);
  const rules = reg.data?.replicationConfiguration?.rules || [];
  const rows = rules.flatMap((r, ri) => r.destinations.map((d) => ({ id: `${ri}-${d.region}-${d.registryId}`, ri, d, filters: (r.repositoryFilters || []).map((x) => x.filter).join(", ") || "All repositories" })));
  const [sel, setSel] = useState([]);
  const put = async (next, msg) => { try { await api.putReplication(next); notify.success(msg); setDlg(false); setSel([]); reg.reload(); } catch (e) { setErr(e); } };
  const add = () => put([...rules, { destinations: [{ region: f.region, registryId: f.registry }], ...(f.prefix ? { repositoryFilters: [{ filterType: "PREFIX_MATCH", filter: f.prefix }] } : {}) }], "Replication rule added.");
  const del = () => put(rules.filter((_, i) => i !== sel[0].ri), "Replication rule removed.");
  return (<>
    <ResourceTable resourceName="Replication rules" items={rows} loading={reg.loading} error={reg.error} onRefresh={reg.reload} trackBy="id" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
      empty={{ title: "No replication rules" }}
      columns={[{ id: "r", header: "Destination Region", isRowHeader: true, cell: (x) => x.d.region }, { id: "a", header: "Destination account", cell: (x) => x.d.registryId }, { id: "f", header: "Repository filter", cell: (x) => x.filters }]}
      actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={del}>Delete</Button><Button variant="primary" onClick={() => { setErr(null); setDlg(true); }}>Add rule</Button></SpaceBetween>} />
    <Modal visible={dlg} onDismiss={() => setDlg(false)} header="Add replication rule" footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setDlg(false)}>Cancel</Button><Button variant="primary" onClick={add}>Save rule</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m"><ErrorAlert error={err} />
        <FormField label="Destination Region"><Input ariaLabel="Destination Region" value={f.region} onChange={({ detail }) => setF({ ...f, region: detail.value })} /></FormField>
        <FormField label="Destination account ID"><Input ariaLabel="Destination account ID" value={f.registry} onChange={({ detail }) => setF({ ...f, registry: detail.value })} /></FormField>
        <FormField label="Repository name prefix filter (optional)"><Input ariaLabel="Prefix filter" value={f.prefix} onChange={({ detail }) => setF({ ...f, prefix: detail.value })} /></FormField></SpaceBetween>
    </Modal></>);
}

function Scanning() {
  const notify = useNotify();
  const c = useAsync(() => api.getScanning(), []);
  const cfg = c.data?.scanningConfiguration || { scanType: "BASIC", rules: [] };
  const [err, setErr] = useState(null);
  const save = async (scanType) => { try { setErr(null); await api.putScanning(scanType, scanType === "ENHANCED" ? [{ scanFrequency: "SCAN_ON_PUSH", repositoryFilters: [{ filter: "*", filterType: "WILDCARD" }] }] : []); notify.success(`Registry scanning set to ${scanType}.`); c.reload(); } catch (e) { setErr(e); } };
  return (<Container header={<Header variant="h2" description="Basic scanning is on-push or manual; enhanced scanning is continuous (Inspector-style).">Scanning configuration</Header>}>
    <SpaceBetween size="s"><ErrorAlert error={err} /><Box>Scan type: <b>{cfg.scanType}</b></Box>
      <SpaceBetween direction="horizontal" size="xs"><Button disabled={cfg.scanType === "BASIC"} onClick={() => save("BASIC")}>Use basic scanning</Button><Button disabled={cfg.scanType === "ENHANCED"} onClick={() => save("ENHANCED")}>Use enhanced scanning</Button></SpaceBetween></SpaceBetween></Container>);
}

export function Registry() {
  return (
    <ContentLayout header={<Header variant="h1" description="Settings that apply to every repository in this Region." actions={<CapabilityBadge id="ecr.registry_v2" />}>Private registry</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Registry URI</Header>}><Box>123456789012.dkr.ecr.us-east-1.&lt;host&gt; (use <code>aws ecr get-login-password</code> to authenticate Docker)</Box></Container>
        <Header variant="h2">Replication</Header><Replication />
        <Scanning />
        <PolicyEditor title="Registry permissions" description="Registry policy (for example, cross-account replication)." load={() => api.getRegistryPolicy()} save={api.putRegistryPolicy} remove={api.deleteRegistryPolicy}
          example={{ Version: "2012-10-17", Statement: [{ Sid: "ReplicationAccessCrossAccount", Effect: "Allow", Principal: { AWS: "arn:aws:iam::123456789012:root" }, Action: ["ecr:CreateRepository", "ecr:ReplicateImage"], Resource: "arn:aws:ecr:us-east-1:123456789012:repository/*" }] }} />
      </SpaceBetween>
    </ContentLayout>
  );
}
