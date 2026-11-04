/* Azure Files: File shares list + share detail (Browse / Snapshots / Properties / Lease) and the File / Queue / Table
 * service settings used by "Resource sharing (CORS)", "Large file shares" and the Endpoints page. Backed by
 * core/azure_files_core.py over ARM (see files.js). */
import { useRef, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Select, Tab, TabList, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowDownload20Regular, ArrowUpload20Regular, Camera20Regular, Delete20Regular, Folder20Regular, Dismiss20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, fmtBytes, InfoBar, Loading } from "../../kit/common.jsx";
import { b64, unb64 } from "../../kit/az08.js";
import * as f from "./files.js";

const fmtGiB = (n) => `${n} GiB`;

export function FileShares({ a, self, query }) {
  if (query.share) return <ShareDetail a={a} name={query.share} self={self} />;
  return <ShareList a={a} self={self} />;
}

function ShareList({ a, self }) {
  const notify = useNotify();
  const [deleted, setDeleted] = useState(false);
  const [create, setCreate] = useState(false);
  const { data, loading, error, reload } = useAsync(() => f.listShares(a, deleted), [a.id, deleted]);
  const rows = (data || []).filter((s) => !!s.properties?.deleted === deleted);
  return (
    <CapabilityContainer id="azure.storage.fileshares" title={`${a.name} | File shares`}>
      <BrowseGrid
        resourceName="file share" rowKey={(r) => r.name} filterPlaceholder="Search file shares by prefix (case-sensitive)"
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={(selected) => <>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setCreate(true)} disabled={deleted}>File share</ToolbarButton>
          <Checkbox checked={deleted} onChange={(_, d) => setDeleted(!!d.checked)} label="Show deleted shares" />
          {deleted && <ToolbarButton disabled={!selected.length} onClick={async () => {
            try { for (const r of selected) await f.restoreShare(a, r.name); notify.success("Restored the selected file shares.", "Restore succeeded"); reload(); } catch (e) { notify.error(e, "Restore failed"); }
          }}>Restore</ToolbarButton>}
        </>}
        onDelete={deleted ? undefined : async (sel) => {
          for (const r of sel) await f.deleteShare(a, r.name, { include: "snapshots" });
          notify.success(`Deleted ${sel.length} file share${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="file-shares.csv"
        columns={[
          { key: "name", label: "Name", render: (r) => (deleted ? r.name : <Link href={`${self}/fileshares?share=${encodeURIComponent(r.name)}`}>{r.name}</Link>) },
          { key: "modified", label: "Last modified", value: (r) => r.properties?.lastModifiedTime },
          { key: "tier", label: "Tier", value: (r) => r.properties?.accessTier },
          { key: "protocol", label: "Protocol", value: (r) => r.properties?.enabledProtocols },
          { key: "quota", label: "Quota", value: (r) => fmtGiB(r.properties?.shareQuota) },
          { key: "usage", label: "Used", value: (r) => fmtBytes(r.properties?.shareUsageBytes || 0) },
          ...(deleted ? [{ key: "left", label: "Days left", value: (r) => r.properties?.remainingRetentionDays }] : []),
        ]}
      />
      <NewShareDialog a={a} open={create} onClose={() => setCreate(false)} onCreated={reload} />
    </CapabilityContainer>
  );
}

function NewShareDialog({ a, open, onClose, onCreated }) {
  const notify = useNotify();
  const premium = a.kind === "FileStorage" || /^premium/i.test(a.sku?.name || "");
  const [name, setName] = useState("");
  const [quota, setQuota] = useState(premium ? "100" : "5120");
  const [tier, setTier] = useState(premium ? "Premium" : "TransactionOptimized");
  const [proto, setProto] = useState("SMB");
  const [squash, setSquash] = useState("NoRootSquash");
  const [busy, setBusy] = useState(false);
  const valid = /^[a-z0-9]+(-[a-z0-9]+)*$/.test(name) && name.length >= 3 && name.length <= 63;
  const go = async () => {
    setBusy(true);
    try {
      await f.putShare(a, name, { shareQuota: Number(quota), accessTier: tier, enabledProtocols: proto, ...(proto === "NFS" ? { rootSquash: squash } : {}) });
      notify.success(`Created file share '${name}'.`, "File share created");
      setName(""); onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to create file share"); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="New file share">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>New file share</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required validationMessage={name && !valid ? "3-63 characters: lower-case letters, numbers and single hyphens." : undefined}>
                <Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Share name" /></Field>
              <Field label="Tier"><Select value={tier} onChange={(_, d) => setTier(d.value)} aria-label="Tier" disabled={premium}>
                {premium ? <option value="Premium">Premium</option> : ["TransactionOptimized", "Hot", "Cool"].map((t) => <option key={t} value={t}>{t}</option>)}
              </Select></Field>
              <Field label="Provisioned / maximum capacity (GiB)" hint={premium ? "Minimum 100 GiB." : "Up to 5120 GiB; 102400 with large file shares enabled."}>
                <Input type="number" value={quota} onChange={(_, d) => setQuota(d.value)} aria-label="Quota" /></Field>
              <Field label="Enabled protocol" hint="NFS requires a premium FileStorage account."><Select value={proto} onChange={(_, d) => setProto(d.value)} aria-label="Protocol">
                <option value="SMB">SMB</option><option value="NFS" disabled={!premium}>NFS</option></Select></Field>
              {proto === "NFS" && <Field label="Root squash"><Select value={squash} onChange={(_, d) => setSquash(d.value)} aria-label="Root squash">
                {["NoRootSquash", "RootSquash", "AllSquash"].map((t) => <option key={t} value={t}>{t}</option>)}</Select></Field>}
            </div>
          </DialogContent>
          <DialogActions><Button appearance="primary" disabled={busy || !valid} onClick={go}>Create</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function ShareDetail({ a, name, self }) {
  const [tab, setTab] = useState("browse");
  const share = useAsync(() => f.getShare(a, name), [a.id, name]);
  const p = share.data?.properties || {};
  return (
    <CapabilityContainer id="azure.storage.fileshares" title={`${a.name} | ${name}`}>
      <p style={{ fontSize: 13 }}><Link href={`${self}/fileshares`}>File shares</Link> / {name}</p>
      <ErrorBar error={share.error} />
      {share.loading && !share.data ? <Loading /> : (
        <>
          <p className="vy-muted" style={{ fontSize: 12 }}>{p.enabledProtocols} · {p.accessTier} · {fmtBytes(p.shareUsageBytes || 0)} of {fmtGiB(p.shareQuota)} · lease {p.leaseState}</p>
          <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="File share tabs">
            <Tab value="browse">Browse</Tab><Tab value="snapshots">Snapshots</Tab><Tab value="properties">Properties</Tab><Tab value="lease">Lease</Tab>
          </TabList>
          {tab === "browse" && <Browse a={a} name={name} reload={share.reload} />}
          {tab === "snapshots" && <Snapshots a={a} name={name} reload={share.reload} />}
          {tab === "properties" && <ShareProps a={a} name={name} p={p} reload={share.reload} />}
          {tab === "lease" && <Lease a={a} name={name} reload={share.reload} />}
        </>
      )}
    </CapabilityContainer>
  );
}

function Browse({ a, name, reload: reloadShare, snapshot }) {
  const notify = useNotify();
  const [path, setPath] = useState("");
  const [mk, setMk] = useState(false);
  const [dir, setDir] = useState("");
  const fileRef = useRef(null);
  const { data, loading, error, reload } = useAsync(() => f.listDir(a, name, path, snapshot), [a.id, name, path, snapshot]);
  const crumbs = path ? path.split("/") : [];
  const join = (n) => (path ? `${path}/${n}` : n);
  const done = () => { reload(); reloadShare?.(); };
  const onFile = async (e) => {
    const file = e.target.files?.[0]; if (!file) return;
    try { await f.upload(a, name, join(file.name), b64(await file.arrayBuffer()), file.type || undefined); notify.success(`Uploaded ${file.name}.`, "Upload succeeded"); done(); }
    catch (err) { notify.error(err, "Upload failed"); } finally { e.target.value = ""; }
  };
  const download = async (n) => {
    try {
      const r = await f.readFile(a, name, join(n), snapshot);
      const url = URL.createObjectURL(new Blob([unb64(r.contentBase64)], { type: r.contentType || "application/octet-stream" }));
      const el = document.createElement("a"); el.href = url; el.download = n; el.click(); URL.revokeObjectURL(url);
    } catch (err) { notify.error(err, "Download failed"); }
  };
  return (
    <div style={{ marginTop: 12 }}>
      <div className="vy-cmdbar" role="toolbar" aria-label="File share commands">
        {!snapshot && <>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setMk(true)}>Add directory</ToolbarButton>
          <ToolbarButton icon={<ArrowUpload20Regular />} onClick={() => fileRef.current?.click()}>Upload</ToolbarButton>
          <input ref={fileRef} type="file" hidden onChange={onFile} aria-label="Upload file" />
        </>}
      </div>
      <p style={{ fontSize: 13 }}>
        <Link as="button" onClick={() => setPath("")}>{name}</Link>
        {crumbs.map((c, i) => <span key={i}> / <Link as="button" onClick={() => setPath(crumbs.slice(0, i + 1).join("/"))}>{c}</Link></span>)}
      </p>
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <table className="vy-grid">
          <thead><tr><th>Name</th><th>Type</th><th>Size</th><th>Last modified</th><th /></tr></thead>
          <tbody>
            {(data || []).length ? data.map((r) => (
              <tr key={r.name}>
                <td>{r.type === "directory" ? <Link as="button" onClick={() => setPath(join(r.name))}><Folder20Regular /> {r.name}</Link> : r.name}</td>
                <td>{r.type}</td><td>{r.type === "file" ? fmtBytes(r.size) : "--"}</td><td>{r.lastModified}</td>
                <td>
                  {r.type === "file" && <Button appearance="subtle" icon={<ArrowDownload20Regular />} aria-label={`Download ${r.name}`} onClick={() => download(r.name)} />}
                  {!snapshot && <Button appearance="subtle" icon={<Delete20Regular />} aria-label={`Delete ${r.name}`} onClick={async () => {
                    try { await f.deletePath(a, name, join(r.name)); done(); } catch (err) { notify.error(err, "Delete failed"); }
                  }} />}
                </td>
              </tr>
            )) : <tr><td colSpan={5} className="vy-muted">This directory is empty.</td></tr>}
          </tbody>
        </table>
      )}
      <Dialog open={mk} onOpenChange={(_, d) => !d.open && setMk(false)}>
        <DialogSurface aria-label="Add directory"><DialogBody>
          <DialogTitle>Add directory</DialogTitle>
          <DialogContent><Field label="Directory name"><Input value={dir} onChange={(_, d) => setDir(d.value)} aria-label="Directory name" /></Field></DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!dir} onClick={async () => { try { await f.mkdir(a, name, join(dir)); setMk(false); setDir(""); done(); } catch (err) { notify.error(err, "Failed to create directory"); } }}>OK</Button>
            <Button onClick={() => setMk(false)}>Cancel</Button>
          </DialogActions>
        </DialogBody></DialogSurface>
      </Dialog>
    </div>
  );
}

function Snapshots({ a, name, reload: reloadShare }) {
  const notify = useNotify();
  const [view, setView] = useState(null);
  const { data, loading, error, reload } = useAsync(() => f.listSnapshots(a, name), [a.id, name]);
  return (
    <div style={{ marginTop: 12 }}>
      <div className="vy-cmdbar" role="toolbar" aria-label="Snapshot commands">
        <ToolbarButton icon={<Camera20Regular />} onClick={async () => { try { await f.snapshotShare(a, name); notify.success("Snapshot created.", "Snapshot created"); reload(); reloadShare(); } catch (e) { notify.error(e, "Snapshot failed"); } }}>Add snapshot</ToolbarButton>
      </div>
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <table className="vy-grid">
          <thead><tr><th>Snapshot</th><th>Used</th><th /></tr></thead>
          <tbody>
            {(data || []).length ? data.map((s) => (
              <tr key={s.snapshotTime}>
                <td><Link as="button" onClick={() => setView(view === s.snapshotTime ? null : s.snapshotTime)}>{s.snapshotTime}</Link></td>
                <td>{fmtBytes(s.usageBytes)}</td>
                <td><Button appearance="subtle" icon={<Delete20Regular />} aria-label="Delete snapshot" onClick={async () => { await f.deleteSnapshot(a, name, s.snapshotTime); if (view === s.snapshotTime) setView(null); reload(); }} /></td>
              </tr>
            )) : <tr><td colSpan={3} className="vy-muted">No snapshots.</td></tr>}
          </tbody>
        </table>
      )}
      {view && <><h4>Contents at {view}</h4><Browse a={a} name={name} snapshot={view} /></>}
    </div>
  );
}

function ShareProps({ a, name, p, reload }) {
  const notify = useNotify();
  const premium = a.kind === "FileStorage" || /^premium/i.test(a.sku?.name || "");
  const [quota, setQuota] = useState(String(p.shareQuota));
  const [tier, setTier] = useState(p.accessTier);
  const [busy, setBusy] = useState(false);
  return (
    <div style={{ marginTop: 12, maxWidth: 520, display: "flex", flexDirection: "column", gap: 12 }}>
      <Field label="Protocol"><Input readOnly value={p.enabledProtocols || ""} /></Field>
      {p.rootSquash && <Field label="Root squash"><Input readOnly value={p.rootSquash} /></Field>}
      <Field label="Quota (GiB)"><Input type="number" value={quota} onChange={(_, d) => setQuota(d.value)} aria-label="Quota" /></Field>
      <Field label="Tier"><Select value={tier} onChange={(_, d) => setTier(d.value)} aria-label="Access tier" disabled={premium}>
        {(premium ? ["Premium"] : ["TransactionOptimized", "Hot", "Cool"]).map((t) => <option key={t} value={t}>{t}</option>)}</Select></Field>
      <div><Button appearance="primary" disabled={busy} onClick={async () => {
        setBusy(true);
        try { await f.putShare(a, name, { shareQuota: Number(quota), accessTier: tier }); notify.success("File share updated.", "Saved"); reload(); } catch (e) { notify.error(e, "Update failed"); } finally { setBusy(false); }
      }}>Save</Button></div>
    </div>
  );
}

function Lease({ a, name, reload }) {
  const notify = useNotify();
  const [id, setId] = useState("");
  const act = async (action) => {
    try { const r = await f.lease(a, name, { action, leaseId: id || undefined }); if (r.leaseId) setId(r.leaseId); notify.success(`Lease ${action} succeeded.`, "Lease"); reload(); } catch (e) { notify.error(e, `Lease ${action} failed`); }
  };
  return (
    <div style={{ marginTop: 12, maxWidth: 520, display: "flex", flexDirection: "column", gap: 12 }}>
      <Field label="Lease ID"><Input value={id} onChange={(_, d) => setId(d.value)} aria-label="Lease ID" /></Field>
      <div style={{ display: "flex", gap: 8 }}>{["acquire", "renew", "release", "break"].map((x) => <Button key={x} onClick={() => act(x)}>{x[0].toUpperCase() + x.slice(1)}</Button>)}</div>
    </div>
  );
}

/** File service settings: soft delete retention + SMB settings (+ CORS via the shared Cors tab). */
export function FileServiceSettings({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => f.getFileService(a), [a.id]);
  const pol = data?.properties?.shareDeleteRetentionPolicy || {};
  const [days, setDays] = useState(null);
  const smb = data?.properties?.protocolSettings?.smb || {};
  if (loading) return <Loading />;
  return (
    <section className="vy-section" style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: 10 }}>
      <h3>Share soft delete and SMB settings</h3>
      <ErrorBar error={error} />
      <Checkbox checked={!!pol.enabled} label="Enable soft delete for file shares" onChange={async (_, d) => {
        try { await f.putFileService(a, { shareDeleteRetentionPolicy: { enabled: !!d.checked, days: Number(days ?? pol.days ?? 7) } }); reload(); } catch (e) { notify.error(e, "Update failed"); }
      }} />
      {pol.enabled && <Field label="Days to retain deleted file shares">
        <Input type="number" value={String(days ?? pol.days ?? 7)} onChange={(_, d) => setDays(d.value)} aria-label="Days to retain deleted file shares"
          onBlur={async () => { if (days == null) return; try { await f.putFileService(a, { shareDeleteRetentionPolicy: { enabled: true, days: Number(days) } }); reload(); } catch (e) { notify.error(e, "Update failed"); } }} /></Field>}
      <Field label="SMB versions"><Input readOnly value={smb.versions || ""} /></Field>
      <Field label="SMB authentication methods"><Input readOnly value={smb.authenticationMethods || ""} /></Field>
      <Field label="SMB multichannel"><Input readOnly value={smb.multichannel?.enabled ? "Enabled" : "Disabled"} /></Field>
    </section>
  );
}

/** CORS rules for the File / Queue / Table service (ARM sub-resources; stored + validated, not evaluated on data requests). */
export function ServiceCors({ a, kind, title }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => f.getService(a, kind), [a.id, kind]);
  const rules = data?.properties?.cors?.corsRules || [];
  const [origins, setOrigins] = useState("*");
  const [method, setMethod] = useState("GET");
  const save = async (next) => { try { await f.putServiceCors(a, kind, next); reload(); } catch (e) { notify.error(e, "Saving CORS rules failed"); } };
  return (
    <section className="vy-section" aria-label={title}>
      <h3>{title}</h3>
      <InfoBar>CORS rules are stored on the account's {kind}/default resource and validated; the Vyomi {title.split(" ")[0]} data plane does not answer preflight requests with them.</InfoBar>
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <table className="vy-grid">
          <thead><tr><th>Allowed origins</th><th>Allowed methods</th><th>Max age</th><th /></tr></thead>
          <tbody>
            {rules.length ? rules.map((r, i) => (
              <tr key={i}><td>{r.allowedOrigins.join(", ")}</td><td>{r.allowedMethods.join(", ")}</td><td>{r.maxAgeInSeconds}</td>
                <td><Button appearance="subtle" icon={<Delete20Regular />} aria-label="Remove rule" onClick={() => save(rules.filter((_, j) => j !== i))} /></td></tr>
            )) : <tr><td colSpan={4} className="vy-muted">No CORS rules have been added.</td></tr>}
          </tbody>
        </table>
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", marginTop: 8 }}>
        <Field label="Allowed origins"><Input value={origins} onChange={(_, d) => setOrigins(d.value)} aria-label={`${title} allowed origins`} /></Field>
        <Field label="Method"><Select value={method} onChange={(_, d) => setMethod(d.value)} aria-label={`${title} method`}>{["GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS"].map((m) => <option key={m}>{m}</option>)}</Select></Field>
        <Button onClick={() => save([...rules, { allowedOrigins: origins.split(",").map((s) => s.trim()).filter(Boolean), allowedMethods: [method], allowedHeaders: ["*"], exposedHeaders: ["*"], maxAgeInSeconds: 200 }])}>Add rule</Button>
      </div>
    </section>
  );
}
