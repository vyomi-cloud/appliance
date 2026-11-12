/* A generic "child resources" section for ARM blades: list a collection, create via a dialog whose fields map to a PUT body,
 * delete the selected row. Real ARM validation errors from the core surface in the dialog. Used by Front Door / CDN profiles and
 * Network Manager (core/azure_netcfg_core.py). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, Textarea } from "@fluentui/react-components";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { restJson } from "../../common/wire.js";
import { ErrorBar, InfoBar, Loading } from "./common.jsx";

const csv = (s) => String(s || "").split(",").map((x) => x.trim()).filter(Boolean);
export const readField = (f, v) => (f.type === "number" ? (v === "" || v == null ? undefined : Number(v)) : f.type === "csv" ? csv(v) : f.type === "json" ? (v ? JSON.parse(v) : undefined) : v);

export default function ArmChildren({ title, path, version, fields, build, columns, noun, note, canCreate = true, extraActions, onSelect, selectedName, rowName = (r) => r.name }) {
  const notify = useNotify();
  const list = useAsync(async () => (await restJson("GET", path, { query: { "api-version": version } })).value || [], [path]);
  const [open, setOpen] = useState(false);
  const [vals, setVals] = useState({});
  const [err, setErr] = useState(null);
  const [sel, setSel] = useState(null);
  const init = () => Object.fromEntries(fields.map((f) => [f.key, f.def ?? (f.options ? f.options[0] : "")]));
  const create = async () => {
    setErr(null);
    try {
      const parsed = Object.fromEntries(fields.map((f) => [f.key, readField(f, vals[f.key])]));
      const { name, body } = build(parsed);
      if (!name) throw new Error(`${noun} name is required.`);
      await restJson("PUT", `${path}/${encodeURIComponent(name)}`, { query: { "api-version": version }, body });
      notify.success(`${noun} '${name}' created.`, `Create ${noun}`); setOpen(false); list.reload();
    } catch (e) { setErr(e); }
  };
  const del = async () => {
    try { await restJson("DELETE", `${path}/${encodeURIComponent(sel)}`, { query: { "api-version": version } }); notify.success(`${noun} '${sel}' deleted.`, `Delete ${noun}`); setSel(null); list.reload(); }
    catch (e) { notify.error(e, `Delete ${noun} failed`); }
  };
  const rows = list.data || [];
  return (
    <section className="vy-section" style={{ marginBottom: 24 }}>
      <h3>{title}</h3>
      {note && <InfoBar title={title}>{note}</InfoBar>}
      <div className="vy-cmdbar" role="toolbar" aria-label={`${title} commands`}>
        {canCreate && <Button size="small" appearance="primary" onClick={() => { setVals(init()); setErr(null); setOpen(true); }}>{`Add ${noun}`}</Button>}
        <Button size="small" disabled={!sel} onClick={del}>{`Delete ${noun}`}</Button>
        {extraActions?.(sel, list.reload)}
        <Button size="small" onClick={list.reload}>Refresh</Button>
      </div>
      {list.loading && !list.data ? <Loading /> : list.error ? <ErrorBar error={list.error} title={`Could not list ${title.toLowerCase()}`} /> : (
        <table className="vy-grid" aria-label={title}><thead><tr><th /><th>Name</th>{columns.map((c) => <th key={c.label}>{c.label}</th>)}</tr></thead><tbody>
          {rows.length === 0 ? <tr><td colSpan={columns.length + 2} className="vy-muted">{`No ${title.toLowerCase()}.`}</td></tr> : rows.map((r) => (
            <tr key={r.id} className={selectedName === rowName(r) ? "selected" : undefined}>
              <td><input type="radio" name={`sel-${title}`} aria-label={`Select ${rowName(r)}`} checked={sel === rowName(r)} onChange={() => { setSel(rowName(r)); onSelect?.(rowName(r)); }} /></td>
              <td>{rowName(r)}</td>{columns.map((c) => <td key={c.label}>{String(c.value(r) ?? "")}</td>)}
            </tr>))}
        </tbody></table>)}
      <Dialog open={open} onOpenChange={(_, d) => !d.open && setOpen(false)}>
        <DialogSurface aria-label={`Add ${noun}`}><DialogBody><DialogTitle>{`Add ${noun}`}</DialogTitle>
          <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 12 }}><ErrorBar error={err} title="Operation failed" />
            {fields.map((f) => (
              <Field key={f.key} label={f.label} hint={f.hint} required={f.required}>
                {f.options ? <Select aria-label={f.label} value={vals[f.key] ?? ""} onChange={(_, d) => setVals({ ...vals, [f.key]: d.value })}>{f.options.map((o) => <option key={o} value={o}>{o}</option>)}</Select>
                  : f.type === "json" ? <Textarea aria-label={f.label} value={vals[f.key] ?? ""} onChange={(_, d) => setVals({ ...vals, [f.key]: d.value })} />
                  : <Input aria-label={f.label} type={f.type === "number" ? "number" : "text"} value={vals[f.key] ?? ""} onChange={(_, d) => setVals({ ...vals, [f.key]: d.value })} />}
              </Field>))}
          </div></DialogContent>
          <DialogActions><Button appearance="primary" onClick={create}>Add</Button><Button onClick={() => setOpen(false)}>Cancel</Button></DialogActions></DialogBody></DialogSurface>
      </Dialog>
    </section>
  );
}
