/* Generic list + create/delete/action-with-form page used by the VPN / Traffic Mirroring / TGW-extras pages.
 * Every page is a real list over the native EC2 Query wire; forms are driven by a field spec. */
import { useEffect, useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import Textarea from "@cloudscape-design/components/textarea";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tabs from "@cloudscape-design/components/tabs";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";

/** field: {key,label,type:"text"|"select"|"checkbox",required,placeholder,options:()=>Promise<[{value,label}]>|[...],default,description} */
function Field({ f, values, set }) {
  const opts = useAsync(async () => (typeof f.options === "function" ? f.options(values) : f.options || []), [f.key, f.type === "select" ? JSON.stringify(f.dep ? values[f.dep] : "") : ""]);
  const v = values[f.key];
  if (f.type === "textarea") return (
    <FormField label={f.label + (f.required ? "" : " - optional")} description={f.description}>
      <Textarea value={v ?? ""} rows={f.rows || 6} placeholder={f.placeholder} ariaLabel={f.label} onChange={({ detail }) => set(f.key, detail.value)} />
    </FormField>);
  if (f.type === "checkbox") return <Checkbox checked={!!v} onChange={({ detail }) => set(f.key, detail.checked)}>{f.label}</Checkbox>;
  if (f.type === "select") {
    const options = (opts.data || []).map((o) => (typeof o === "string" ? { value: o, label: o } : o));
    return (
      <FormField label={f.label + (f.required ? "" : " - optional")} description={f.description}>
        <Select selectedOption={options.find((o) => o.value === v) || null} placeholder={f.placeholder || "Choose an option"} options={options} ariaLabel={f.label}
          onChange={({ detail }) => set(f.key, detail.selectedOption.value)} statusType={opts.loading ? "loading" : "finished"} empty="No options" />
      </FormField>
    );
  }
  return (
    <FormField label={f.label + (f.required ? "" : " - optional")} description={f.description}>
      <Input value={v ?? ""} placeholder={f.placeholder} ariaLabel={f.label} onChange={({ detail }) => set(f.key, detail.value)} />
    </FormField>
  );
}

export function FormModal({ header, fields = [], submit, onDismiss, onDone, label = "Create", children }) {
  const notify = useNotify();
  const [values, setValues] = useState(() => Object.fromEntries(fields.filter((f) => f.default !== undefined).map((f) => [f.key, f.default])));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const shown = fields.filter((f) => !f.showIf || f.showIf(values));
  const valid = shown.every((f) => !f.required || (values[f.key] !== undefined && values[f.key] !== ""));
  const go = async () => { setBusy(true); setErr(null); try { await submit(values); onDone?.(); onDismiss(); } catch (e) { setErr(e); notify.error?.(e); } finally { setBusy(false); } };
  return (
    <Modal visible onDismiss={onDismiss} header={header}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!valid} onClick={go}>{label}</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">{err && <ErrorAlert error={err} />}{children}{shown.map((f) => <Field key={f.key} f={f} values={values} set={(k, val) => setValues((s) => ({ ...s, [k]: val }))} />)}</SpaceBetween>
    </Modal>
  );
}

/** Table with actions. props: title, capId, trackBy, load, columns, create:{label,fields,submit}, del:{label,type,run,names}, actions:[{text,fields,submit(sel,values),needs:"one"|"any"}], detail:(row)=>tabs[] */
export function ResourceList({ title, capId, trackBy, load, columns, create, del, actions = [], detail, empty, variant, h2 }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [delOpen, setDelOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [act, setAct] = useState(null);
  const t = useAsync(load, []);
  const refresh = (clear = true) => { if (clear) setSel([]); t.reload(); };
  // keep the selection (and so the detail tabs) across action refreshes: re-map selected rows onto the fresh data
  useEffect(() => { if (t.data) setSel((cur) => cur.map((c) => t.data.find((d) => d[trackBy] === c[trackBy])).filter(Boolean)); }, [t.data]);
  const body = (
    <>
      <ResourceTable resourceName={title} description={capId ? <CapabilityBadge id={capId} /> : undefined} items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload}
        trackBy={trackBy} selectionType="multi" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Search" variant={variant}
        empty={empty ? { title: `No ${title.toLowerCase()}`, subtitle: empty } : undefined} columns={columns}
        actions={<SpaceBetween direction="horizontal" size="xs">
          {actions.map((a) => <Button key={a.text} disabled={a.needs === "one" ? sel.length !== 1 : !sel.length} onClick={() => setAct(a)}>{a.text}</Button>)}
          {del && <Button disabled={!sel.length} onClick={() => setDelOpen(true)}>{del.label || "Delete"}</Button>}
          {create && <Button variant="primary" onClick={() => setCreateOpen(true)}>{create.label}</Button>}
        </SpaceBetween>} />
      {del && <DeleteModal visible={delOpen} resourceType={del.type || title.toLowerCase()} names={sel.map((s) => s[trackBy])} confirmText="delete" onDismiss={() => setDelOpen(false)}
        onConfirm={async () => { try { for (const s of sel) await del.run(s); notify.success(`${del.type || title} deleted.`); } catch (e) { notify.error(e); } refresh(); }} />}
      {createOpen && <FormModal header={create.label} fields={create.fields} submit={create.submit} onDismiss={() => setCreateOpen(false)} onDone={() => { notify.success(create.done || "Created."); t.reload(); }} />}
      {act && <FormModal header={act.text} label={act.label || "Confirm"} fields={act.fields || []} submit={(v) => act.submit(sel, v)} onDismiss={() => setAct(null)} onDone={() => { notify.success(`${act.text}: done.`); refresh(false); }} />}
      {detail && sel.length === 1 && <Tabs tabs={detail(sel[0], t.reload)} />}
    </>
  );
  if (h2) return <SpaceBetween size="l">{body}</SpaceBetween>;
  return <ContentLayout header={<Header variant="h1">{title}</Header>}><SpaceBetween size="l">{body}</SpaceBetween></ContentLayout>;
}
