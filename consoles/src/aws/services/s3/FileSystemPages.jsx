/* S3 file systems (Amazon S3 Files: bucket-backed file systems with mount targets, access points, policy, sync rules, and a file
 * browser over the bucket's objects) and Access Points for FSx (FSx for OpenZFS volumes exposed as S3 access points).
 * Capability ids: s3.account.file-systems, s3.account.access-points-fsx. Backed by core/s3files_core.py. */
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
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import * as f from "./filesApi.js";
import * as api from "./api.js";

const CAP = "s3.account.file-systems";
const CAP_FSX = "s3.account.access-points-fsx";
const Loading = () => <StatusIndicator type="loading">Loading</StatusIndicator>;
const Empty = ({ title, children }) => <Box textAlign="center" color="inherit"><b>{title}</b><Box variant="p" color="inherit">{children}</Box></Box>;
const when = (t) => (t ? new Date(t * 1000).toLocaleString() : "-");
const opt = (v, l) => ({ value: v, label: l || v });

// ───────────────────────────── Files tab ─────────────────────────────
function FilesTab({ fs }) {
  const notify = useNotify();
  const [path, setPath] = useState("/");
  const list = useAsync(() => f.listFiles(fs.fileSystemId, path), [fs.fileSystemId, path]);
  const [sel, setSel] = useState([]);
  const [add, setAdd] = useState(null);
  const [view, setView] = useState(null);
  const join = (n) => (path === "/" ? "" : path) + "/" + n;
  const rows = list.data || [];
  const up = path === "/" ? "/" : path.slice(0, path.lastIndexOf("/")) || "/";
  const run = async (fn, msg) => { try { await fn(); notify.success(msg); list.reload(); } catch (e) { notify.error(e); } };
  return (
    <SpaceBetween size="s">
      <Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button iconName="refresh" ariaLabel="Refresh files" onClick={list.reload} />
        <Button disabled={path === "/"} onClick={() => { setPath(up); setSel([]); }}>Up</Button>
        <Button disabled={sel.length !== 1 || sel[0].type !== "file"} onClick={async () => { try { setView({ name: sel[0].name, text: await f.readFile(fs.fileSystemId, join(sel[0].name)) }); } catch (e) { notify.error(e); } }}>View</Button>
        <Button disabled={!sel.length} onClick={() => run(async () => { for (const s of sel) if (s.type === "file") await f.deleteFile(fs.fileSystemId, join(s.name)); setSel([]); }, "Successfully deleted the selected file(s).")}>Delete</Button>
        <Button onClick={() => setAdd({ kind: "dir", name: "" })}>New directory</Button>
        <Button variant="primary" onClick={() => setAdd({ kind: "file", name: "", text: "" })}>New file</Button>
      </SpaceBetween></Box>
      <Box variant="code" data-testid="fs-path">{path}</Box>
      {list.loading ? <Loading /> : list.error ? <ErrorAlert error={list.error} />
        : <Table variant="embedded" items={rows} trackBy="name" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
            columnDefinitions={[
              { id: "n", header: "Name", cell: (r) => r.type === "directory" ? <Button variant="inline-link" onClick={() => { setPath(join(r.name)); setSel([]); }}>{r.name}/</Button> : r.name },
              { id: "t", header: "Type", cell: (r) => r.type },
              { id: "s", header: "Size (bytes)", cell: (r) => (r.type === "file" ? r.size : "-") },
              { id: "m", header: "Last modified", cell: (r) => r.lastModified || "-" },
            ]}
            empty={<Empty title="Empty directory">Create a file or directory, or put objects under this file system's prefix with the S3 API.</Empty>} />}
      <Modal visible={!!add} onDismiss={() => setAdd(null)} header={add?.kind === "dir" ? "New directory" : "New file"}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAdd(null)}>Cancel</Button>
          <Button variant="primary" disabled={!add?.name} onClick={async () => {
            const a = add; setAdd(null);
            await run(() => (a.kind === "dir" ? f.makeDir(fs.fileSystemId, join(a.name)) : f.writeFile(fs.fileSystemId, join(a.name), a.text)), `Successfully created ${a.name}.`);
          }}>Create</Button>
        </SpaceBetween></Box>}>
        {add && <SpaceBetween size="m">
          <FormField label="Name"><Input value={add.name} ariaLabel="File or directory name" onChange={({ detail: d }) => setAdd({ ...add, name: d.value })} /></FormField>
          {add.kind === "file" && <FormField label="Contents"><Textarea value={add.text} ariaLabel="File contents" rows={6} onChange={({ detail: d }) => setAdd({ ...add, text: d.value })} /></FormField>}
        </SpaceBetween>}
      </Modal>
      <Modal visible={!!view} onDismiss={() => setView(null)} header={view?.name || ""} footer={<Box float="right"><Button onClick={() => setView(null)}>Close</Button></Box>}>
        <pre style={{ margin: 0, whiteSpace: "pre-wrap" }} data-testid="fs-file-text">{view?.text}</pre>
      </Modal>
    </SpaceBetween>
  );
}

// ───────────────────────────── Mount targets / access points ─────────────────────────────
function MountTargetsTab({ fs }) {
  const notify = useNotify();
  const list = useAsync(() => f.listMountTargets(fs.fileSystemId), [fs.fileSystemId]);
  const subs = useAsync(() => f.describeSubnets(), []);
  const sgs = useAsync(() => f.describeSecurityGroups(), []);
  const [sel, setSel] = useState([]);
  const [add, setAdd] = useState(null);
  const subOpts = (subs.data || []).map((s) => opt(s.subnetId, `${s.subnetId} (${s.availabilityZone}, ${s.cidrBlock})`));
  const sgOpts = (sgs.data || []).map((g) => ({ value: g.GroupId || g.groupId, label: `${g.GroupId || g.groupId} (${g.GroupName || g.groupName})` }));
  return (
    <SpaceBetween size="s">
      <Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button iconName="refresh" ariaLabel="Refresh mount targets" onClick={list.reload} />
        <Button disabled={sel.length !== 1} onClick={async () => { try { await f.deleteMountTarget(sel[0].mountTargetId); notify.success("Successfully deleted the mount target."); setSel([]); list.reload(); } catch (e) { notify.error(e); } }}>Delete</Button>
        <Button variant="primary" onClick={() => setAdd({ subnet: null, sgs: [] })}>Create mount target</Button>
      </SpaceBetween></Box>
      {list.loading ? <Loading /> : list.error ? <ErrorAlert error={list.error} />
        : <Table variant="embedded" items={list.data || []} trackBy="mountTargetId" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
            columnDefinitions={[
              { id: "i", header: "Mount target ID", cell: (r) => r.mountTargetId }, { id: "z", header: "Availability Zone", cell: (r) => r.availabilityZoneName },
              { id: "s", header: "Subnet", cell: (r) => r.subnetId }, { id: "ip", header: "IP address", cell: (r) => r.ipAddress },
              { id: "g", header: "Security groups", cell: (r) => (r.securityGroups || []).join(", ") || "-" }, { id: "st", header: "Status", cell: (r) => <StatusIndicator type="success">{r.status}</StatusIndicator> },
            ]}
            empty={<Empty title="No mount targets">Create one in each Availability Zone you mount from.</Empty>} />}
      <Modal visible={!!add} onDismiss={() => setAdd(null)} header="Create mount target"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAdd(null)}>Cancel</Button>
          <Button variant="primary" disabled={!add?.subnet} onClick={async () => {
            try { await f.createMountTarget(fs.fileSystemId, { subnetId: add.subnet.value, securityGroups: add.sgs.map((o) => o.value) }); notify.success("Successfully created the mount target."); setAdd(null); list.reload(); } catch (e) { notify.error(e); }
          }}>Create mount target</Button>
        </SpaceBetween></Box>}>
        {add && <SpaceBetween size="m">
          <FormField label="Subnet"><Select selectedOption={add.subnet} options={subOpts} placeholder="Choose a subnet" onChange={({ detail }) => setAdd({ ...add, subnet: detail.selectedOption })} /></FormField>
          <FormField label="Security groups (optional)"><Select selectedOption={add.sgs[0] || null} options={sgOpts} placeholder="Choose a security group" onChange={({ detail }) => setAdd({ ...add, sgs: [detail.selectedOption] })} /></FormField>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}

function AccessPointsTab({ fs }) {
  const notify = useNotify();
  const list = useAsync(() => f.listFsAccessPoints(fs.fileSystemId), [fs.fileSystemId]);
  const [sel, setSel] = useState([]);
  const [add, setAdd] = useState(null);
  return (
    <SpaceBetween size="s">
      <Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button iconName="refresh" ariaLabel="Refresh access points" onClick={list.reload} />
        <Button disabled={sel.length !== 1} onClick={async () => { try { await f.deleteFsAccessPoint(sel[0].accessPointId); notify.success("Successfully deleted the access point."); setSel([]); list.reload(); } catch (e) { notify.error(e); } }}>Delete</Button>
        <Button variant="primary" onClick={() => setAdd({ name: "", uid: "1000", gid: "1000", path: "/", perms: "0755" })}>Create access point</Button>
      </SpaceBetween></Box>
      {list.loading ? <Loading /> : list.error ? <ErrorAlert error={list.error} />
        : <Table variant="embedded" items={list.data || []} trackBy="accessPointId" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
            columnDefinitions={[
              { id: "i", header: "Access point ID", cell: (r) => r.accessPointId }, { id: "n", header: "Name", cell: (r) => r.name || "-" },
              { id: "u", header: "POSIX user", cell: (r) => (r.posixUser ? `${r.posixUser.uid}:${r.posixUser.gid}` : "-") }, { id: "p", header: "Root directory", cell: (r) => r.rootDirectory?.path },
              { id: "s", header: "Status", cell: (r) => <StatusIndicator type="success">{r.status}</StatusIndicator> },
            ]}
            empty={<Empty title="No access points">Access points enforce a POSIX identity and root directory for an application.</Empty>} />}
      <Modal visible={!!add} onDismiss={() => setAdd(null)} header="Create access point"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAdd(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            try {
              await f.createFsAccessPoint(fs.fileSystemId, { ...(add.name ? { name: add.name } : {}), posixUser: { uid: Number(add.uid), gid: Number(add.gid) },
                rootDirectory: { path: add.path, creationPermissions: { ownerUid: Number(add.uid), ownerGid: Number(add.gid), permissions: add.perms } } });
              notify.success("Successfully created the access point."); setAdd(null); list.reload();
            } catch (e) { notify.error(e); }
          }}>Create access point</Button>
        </SpaceBetween></Box>}>
        {add && <SpaceBetween size="m">
          <FormField label="Name (optional)"><Input value={add.name} ariaLabel="Access point name" onChange={({ detail: d }) => setAdd({ ...add, name: d.value })} /></FormField>
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="POSIX user ID"><Input value={add.uid} ariaLabel="POSIX user ID" inputMode="numeric" onChange={({ detail: d }) => setAdd({ ...add, uid: d.value })} /></FormField>
            <FormField label="POSIX group ID"><Input value={add.gid} ariaLabel="POSIX group ID" inputMode="numeric" onChange={({ detail: d }) => setAdd({ ...add, gid: d.value })} /></FormField>
          </SpaceBetween>
          <FormField label="Root directory path"><Input value={add.path} ariaLabel="Root directory path" onChange={({ detail: d }) => setAdd({ ...add, path: d.value })} /></FormField>
          <FormField label="Creation permissions (octal)"><Input value={add.perms} ariaLabel="Creation permissions" onChange={({ detail: d }) => setAdd({ ...add, perms: d.value })} /></FormField>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}

function SettingsTab({ fs }) {
  const notify = useNotify();
  const pol = useAsync(() => f.getFsPolicy(fs.fileSystemId), [fs.fileSystemId]);
  const sync = useAsync(() => f.getSync(fs.fileSystemId), [fs.fileSystemId]);
  const [polEdit, setPolEdit] = useState(null);
  const [days, setDays] = useState(null);
  const exp = sync.data?.expirationDataRules?.[0]?.daysAfterLastAccess;
  return (
    <SpaceBetween size="l">
      <KeyValue title="Synchronization" columns={2} actions={<Button onClick={() => setDays(String(exp || 30))}>Edit expiration</Button>}
        items={[["Import rules", (sync.data?.importDataRules || []).map((r) => `${r.trigger}${r.sizeLessThan ? ` (< ${r.sizeLessThan} bytes)` : ""}`).join("; ") || "None"],
          ["Expire data after last access", exp ? `${exp} days` : "Never"]]} />
      <KeyValue title="File system policy" columns={1}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!pol.data} onClick={async () => { try { await f.deleteFsPolicy(fs.fileSystemId); notify.success("Successfully deleted the file system policy."); pol.reload(); } catch (e) { notify.error(e); } }}>Delete</Button>
          <Button onClick={() => setPolEdit(pol.data || '{"Version":"2012-10-17","Statement":[]}')}>Edit</Button></SpaceBetween>}
        items={[["Policy", pol.data ? <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{pol.data}</pre> : "No file system policy."]]} />
      <Modal visible={polEdit !== null} onDismiss={() => setPolEdit(null)} header="Edit file system policy"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setPolEdit(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { try { await f.putFsPolicy(fs.fileSystemId, polEdit); notify.success("Successfully edited the policy."); setPolEdit(null); pol.reload(); } catch (e) { notify.error(e); } }}>Save changes</Button>
        </SpaceBetween></Box>}>
        <FormField label="Policy (JSON)"><Textarea value={polEdit || ""} ariaLabel="File system policy" rows={10} onChange={({ detail: d }) => setPolEdit(d.value)} /></FormField>
      </Modal>
      <Modal visible={days !== null} onDismiss={() => setDays(null)} header="Edit expiration rule"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setDays(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { try { await f.putSync(fs.fileSystemId, { importDataRules: sync.data?.importDataRules || [], expirationDataRules: [{ daysAfterLastAccess: Number(days) }] }); notify.success("Successfully edited the synchronization configuration."); setDays(null); sync.reload(); } catch (e) { notify.error(e); } }}>Save changes</Button>
        </SpaceBetween></Box>}>
        <FormField label="Days after last access" description="1-365. Stored and validated; Vyomi does not run an expiration job."><Input value={days || ""} ariaLabel="Days after last access" inputMode="numeric" onChange={({ detail: d }) => setDays(d.value)} /></FormField>
      </Modal>
    </SpaceBetween>
  );
}

function FsDetail({ fs }) {
  return (
    <SpaceBetween size="m">
      <KeyValue columns={3} items={[["File system ID", fs.fileSystemId], ["ARN", fs.fileSystemArn], ["Status", <StatusIndicator type="success">{fs.status}</StatusIndicator>],
        ["Bucket", `s3://${fs.bucket}/${fs.prefix}`], ["IAM role", fs.roleArn], ["Created", when(fs.creationTime)]]} />
      <Tabs tabs={[
        { id: "files", label: "Files", content: <FilesTab fs={fs} /> },
        { id: "mt", label: "Mount targets", content: <MountTargetsTab fs={fs} /> },
        { id: "ap", label: "Access points", content: <AccessPointsTab fs={fs} /> },
        { id: "settings", label: "Settings", content: <SettingsTab fs={fs} /> },
      ]} />
    </SpaceBetween>
  );
}

export function FileSystems() {
  const notify = useNotify();
  const list = useAsync(() => f.listFileSystems(), []);
  const buckets = useAsync(() => api.listBuckets(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [saving, setSaving] = useState(false);
  const rows = list.data || [];
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id={CAP} title="File systems" counter={`(${rows.length})`}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh file systems" onClick={list.reload} />
          <Button disabled={sel.length !== 1} onClick={async () => { try { await f.deleteFileSystem(sel[0].fileSystemId); notify.success(`Successfully deleted file system ${sel[0].fileSystemId}.`); setSel([]); list.reload(); } catch (e) { notify.error(e); } }}>Delete</Button>
          <Button variant="primary" onClick={() => setCreate({ bucket: null, prefix: "", role: "arn:aws:iam::123456789012:role/S3FilesRole", name: "" })}>Create file system</Button>
        </SpaceBetween>}>
        {list.loading ? <Loading /> : list.error ? <ErrorAlert error={list.error} />
          : <Table variant="embedded" items={rows} trackBy="fileSystemId" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
              columnDefinitions={[
                { id: "i", header: "File system ID", cell: (r) => r.fileSystemId }, { id: "n", header: "Name", cell: (r) => r.name || "-" },
                { id: "b", header: "Bucket", cell: (r) => `${r.bucket}${r.prefix ? "/" + r.prefix : ""}` },
                { id: "s", header: "Status", cell: (r) => <StatusIndicator type="success">{r.status}</StatusIndicator> }, { id: "c", header: "Created", cell: (r) => when(r.creationTime) },
              ]}
              empty={<Empty title="No file systems">Create a file system to work with a bucket's objects as files and directories.</Empty>} />}
      </CapabilityContainer>
      {sel[0] && <CapabilityContainer id={CAP} title={`File system ${sel[0].fileSystemId}`}><FsDetail key={sel[0].fileSystemId} fs={sel[0]} /></CapabilityContainer>}
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create file system"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} disabled={!create?.bucket} onClick={async () => {
            setSaving(true);
            try {
              const r = await f.createFileSystem({ bucket: create.bucket.value, prefix: create.prefix, roleArn: create.role, name: create.name });
              notify.success(`Successfully created file system ${r.fileSystemId}.${saveNotice(CAP)}`); setCreate(null); list.reload();
            } catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create file system</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Name (optional)"><Input value={create.name} ariaLabel="File system name" onChange={({ detail: d }) => setCreate({ ...create, name: d.value })} /></FormField>
          <FormField label="S3 bucket" description="The file system's files are this bucket's objects."><Select selectedOption={create.bucket} options={(buckets.data || []).map((b) => opt(b.name))} placeholder="Choose a bucket" onChange={({ detail }) => setCreate({ ...create, bucket: detail.selectedOption })} /></FormField>
          <FormField label="Prefix (optional)" description="Scope the file system to a folder in the bucket."><Input value={create.prefix} ariaLabel="Prefix" onChange={({ detail: d }) => setCreate({ ...create, prefix: d.value })} /></FormField>
          <FormField label="IAM role ARN"><Input value={create.role} ariaLabel="IAM role ARN" onChange={({ detail: d }) => setCreate({ ...create, role: d.value })} /></FormField>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}

// ───────────────────────────── Access Points for FSx ─────────────────────────────
function VolumesTab({ onChanged }) {
  const notify = useNotify();
  const vols = useAsync(() => Promise.all([f.fsxVolumes(), f.fsxFileSystems()]), []);
  const subs = useAsync(() => f.describeSubnets(), []);
  const [volumes, systems] = vols.data || [[], []];
  const [sel, setSel] = useState([]);
  const [fsDlg, setFsDlg] = useState(null);
  const [fileDlg, setFileDlg] = useState(null);
  const [files, setFiles] = useState(null);
  const reload = () => { vols.reload(); onChanged(); };
  const subOpts = (subs.data || []).map((s) => opt(s.subnetId, `${s.subnetId} (${s.availabilityZone})`));
  return (
    <SpaceBetween size="s">
      <Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button iconName="refresh" ariaLabel="Refresh volumes" onClick={reload} />
        <Button disabled={sel.length !== 1} onClick={async () => setFiles({ vol: sel[0].VolumeId, rows: await f.fsxListFiles(sel[0].VolumeId) })}>List files</Button>
        <Button disabled={sel.length !== 1} onClick={() => setFileDlg({ path: "/", text: "" })}>Add file</Button>
        <Button disabled={sel.length !== 1} onClick={async () => { try { await f.fsxCreateVolume(sel[0].VolumeId, `vol${Date.now() % 10000}`); notify.success("Successfully created a child volume."); reload(); } catch (e) { notify.error(e); } }}>Create child volume</Button>
        <Button variant="primary" onClick={() => setFsDlg({ capacity: "64", throughput: "160", deployment: "SINGLE_AZ_2", subnet: null })}>Create FSx file system</Button>
      </SpaceBetween></Box>
      {vols.loading ? <Loading /> : vols.error ? <ErrorAlert error={vols.error} />
        : <Table variant="embedded" items={volumes} trackBy="VolumeId" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
            columnDefinitions={[
              { id: "i", header: "Volume ID", cell: (r) => r.VolumeId }, { id: "n", header: "Name", cell: (r) => r.Name }, { id: "f", header: "File system", cell: (r) => r.FileSystemId },
              { id: "p", header: "Path", cell: (r) => r.OpenZFSConfiguration?.VolumePath }, { id: "s", header: "Lifecycle", cell: (r) => <StatusIndicator type="success">{r.Lifecycle}</StatusIndicator> },
            ]}
            empty={<Empty title="No FSx for OpenZFS volumes">Create an FSx file system to get a root volume you can expose through an S3 access point.</Empty>} />}
      {files && <Table variant="embedded" items={files.rows} trackBy="Path" header={<Box variant="awsui-key-label">Files in {files.vol}</Box>}
        columnDefinitions={[{ id: "p", header: "Path", cell: (r) => r.Path }, { id: "s", header: "Size", cell: (r) => r.Size }]} empty={<Empty title="No files">Add a file to see it through the access point.</Empty>} />}
      <Modal visible={!!fsDlg} onDismiss={() => setFsDlg(null)} header="Create FSx for OpenZFS file system"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setFsDlg(null)}>Cancel</Button>
          <Button variant="primary" disabled={!fsDlg?.subnet} onClick={async () => { try { await f.fsxCreateFileSystem({ ...fsDlg, subnetId: fsDlg.subnet.value }); notify.success("Successfully created the FSx file system."); setFsDlg(null); reload(); } catch (e) { notify.error(e); } }}>Create file system</Button>
        </SpaceBetween></Box>}>
        {fsDlg && <SpaceBetween size="m">
          <FormField label="Storage capacity (GiB)" description="64-524288"><Input value={fsDlg.capacity} ariaLabel="Storage capacity" inputMode="numeric" onChange={({ detail: d }) => setFsDlg({ ...fsDlg, capacity: d.value })} /></FormField>
          <FormField label="Throughput capacity (MBps)"><Input value={fsDlg.throughput} ariaLabel="Throughput capacity" inputMode="numeric" onChange={({ detail: d }) => setFsDlg({ ...fsDlg, throughput: d.value })} /></FormField>
          <FormField label="Subnet"><Select selectedOption={fsDlg.subnet} options={subOpts} placeholder="Choose a subnet" onChange={({ detail }) => setFsDlg({ ...fsDlg, subnet: detail.selectedOption })} /></FormField>
        </SpaceBetween>}
      </Modal>
      <Modal visible={!!fileDlg} onDismiss={() => setFileDlg(null)} header="Add file to volume"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setFileDlg(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { try { await f.fsxPutFile(sel[0].VolumeId, fileDlg.path, fileDlg.text); notify.success(`Successfully wrote ${fileDlg.path}.`); setFileDlg(null); setFiles({ vol: sel[0].VolumeId, rows: await f.fsxListFiles(sel[0].VolumeId) }); } catch (e) { notify.error(e); } }}>Add file</Button>
        </SpaceBetween></Box>}>
        {fileDlg && <SpaceBetween size="m">
          <FormField label="File path" description="Stands in for writing over NFS/SMB, which Vyomi does not serve."><Input value={fileDlg.path} ariaLabel="Volume file path" onChange={({ detail: d }) => setFileDlg({ ...fileDlg, path: d.value })} /></FormField>
          <FormField label="Contents"><Textarea value={fileDlg.text} ariaLabel="Volume file contents" rows={5} onChange={({ detail: d }) => setFileDlg({ ...fileDlg, text: d.value })} /></FormField>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}

function ObjectsView({ alias }) {
  const list = useAsync(() => api.listObjects(alias, ""), [alias]);
  const rows = [...(list.data?.folders || []), ...(list.data?.objects || [])];
  return list.loading ? <Loading /> : list.error ? <ErrorAlert error={list.error} />
    : <Table variant="embedded" items={rows} trackBy="key" header={<Box variant="awsui-key-label">Objects served through the access point alias</Box>}
        columnDefinitions={[{ id: "k", header: "Key", cell: (r) => r.key }, { id: "s", header: "Size", cell: (r) => (r.folder ? "-" : r.size) }]}
        empty={<Empty title="No objects">The volume has no files yet.</Empty>} />;
}

export function AccessPointsForFsx() {
  const notify = useNotify();
  const [tab, setTab] = useState("aps");
  const [rev, setRev] = useState(0);
  const list = useAsync(() => Promise.all([f.fsxAttachments(), f.fsxVolumes()]), [rev]);
  const vpcs = useAsync(() => f.describeVpcs(), []);
  const [rows, volumes] = list.data || [[], []];
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(null);
  const [saving, setSaving] = useState(false);
  const reload = () => setRev((x) => x + 1);
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id={CAP_FSX} title="Access Points for FSx">
        <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
          { id: "aps", label: `Access points (${rows.length})`, content: (
            <SpaceBetween size="s">
              <Box float="right"><SpaceBetween direction="horizontal" size="xs">
                <Button iconName="refresh" ariaLabel="Refresh access points" onClick={reload} />
                <Button disabled={sel.length !== 1} onClick={async () => { try { await f.fsxDetach(sel[0].Name); notify.success(`Successfully detached and deleted ${sel[0].Name}.`); setSel([]); reload(); } catch (e) { notify.error(e); } }}>Detach and delete</Button>
                <Button variant="primary" onClick={() => setCreate({ name: "", volume: null, uid: "1001", gid: "1001", vpc: null })}>Create and attach access point</Button>
              </SpaceBetween></Box>
              {list.loading ? <Loading /> : list.error ? <ErrorAlert error={list.error} />
                : <Table variant="embedded" items={rows} trackBy="Name" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
                    columnDefinitions={[
                      { id: "n", header: "Name", cell: (r) => r.Name }, { id: "v", header: "Volume", cell: (r) => r.OpenZFSConfiguration?.VolumeId },
                      { id: "a", header: "Alias", cell: (r) => r.S3AccessPoint?.Alias }, { id: "u", header: "POSIX user", cell: (r) => `${r.OpenZFSConfiguration?.FileSystemIdentity?.PosixUser?.Uid}:${r.OpenZFSConfiguration?.FileSystemIdentity?.PosixUser?.Gid}` },
                      { id: "s", header: "Lifecycle", cell: (r) => <StatusIndicator type="success">{r.Lifecycle}</StatusIndicator> },
                    ]}
                    empty={<Empty title="No access points">Attach an S3 access point to an FSx for OpenZFS volume to reach its files with the S3 API.</Empty>} />}
              {sel[0] && <KeyValue columns={2} items={[["Access point ARN", sel[0].S3AccessPoint?.ResourceARN], ["Alias (use as the bucket name)", sel[0].S3AccessPoint?.Alias],
                ["Network origin", sel[0].S3AccessPoint?.VpcConfiguration ? `VPC ${sel[0].S3AccessPoint.VpcConfiguration.VpcId}` : "Internet"]]} />}
              {sel[0] && <ObjectsView key={sel[0].S3AccessPoint?.Alias} alias={sel[0].S3AccessPoint?.Alias} />}
            </SpaceBetween>) },
          { id: "vols", label: "FSx volumes", content: <VolumesTab onChanged={reload} /> },
        ]} />
      </CapabilityContainer>
      <Modal visible={!!create} onDismiss={() => setCreate(null)} header="Create and attach S3 access point"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(null)}>Cancel</Button>
          <Button variant="primary" loading={saving} disabled={!create?.name || !create?.volume} onClick={async () => {
            setSaving(true);
            try { await f.fsxAttach({ name: create.name, volumeId: create.volume.value, uid: create.uid, gid: create.gid, vpcId: create.vpc?.value }); notify.success(`Successfully attached access point ${create.name}.${saveNotice(CAP_FSX)}`); setCreate(null); reload(); }
            catch (e) { notify.error(e); } finally { setSaving(false); }
          }}>Create and attach</Button>
        </SpaceBetween></Box>}>
        {create && <SpaceBetween size="m">
          <FormField label="Access point name" description="3-51 characters: lowercase letters, numbers, hyphens."><Input value={create.name} ariaLabel="Access point name" onChange={({ detail: d }) => setCreate({ ...create, name: d.value })} /></FormField>
          <FormField label="FSx for OpenZFS volume"><Select selectedOption={create.volume} options={volumes.map((v) => opt(v.VolumeId, `${v.VolumeId} (${v.Name}, ${v.OpenZFSConfiguration?.VolumePath})`))} placeholder="Choose a volume" onChange={({ detail }) => setCreate({ ...create, volume: detail.selectedOption })} /></FormField>
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="POSIX user ID"><Input value={create.uid} ariaLabel="POSIX user ID" inputMode="numeric" onChange={({ detail: d }) => setCreate({ ...create, uid: d.value })} /></FormField>
            <FormField label="POSIX group ID"><Input value={create.gid} ariaLabel="POSIX group ID" inputMode="numeric" onChange={({ detail: d }) => setCreate({ ...create, gid: d.value })} /></FormField>
          </SpaceBetween>
          <FormField label="Network origin" description="Leave empty for Internet."><Select selectedOption={create.vpc} options={(vpcs.data || []).map((v) => opt(v.vpcId))} placeholder="Internet" onChange={({ detail }) => setCreate({ ...create, vpc: detail.selectedOption })} /></FormField>
        </SpaceBetween>}
      </Modal>
    </SpaceBetween>
  );
}
