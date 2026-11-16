/* Bedrock Prompt Management: prompts with variants + versions (CreatePrompt/CreatePromptVersion) and a test run through Converse. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import Input from "@cloudscape-design/components/input";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import DeleteModal from "../../../kit/DeleteModal.jsx";
import { ErrorAlert, KeyValue, fmtDate } from "../../../kit/common.jsx";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import { follow, href, navigate } from "../../../../common/router.js";
import { converse } from "../api.js";
import { CreateModal, Field, ModelSelect, Page, useModelOptions } from "../inferTune/Shared.jsx";
import * as api from "./api.js";

const vars = (t) => [...new Set([...String(t).matchAll(/\{\{\s*([A-Za-z0-9_-]+)\s*\}\}/g)].map((m) => m[1]))];

export function Prompts() {
  const t = useAsync(() => api.listPrompts(), []);
  const models = useModelOptions();
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false);
  const [del, setDel] = useState(false);
  const [name, setName] = useState(""), [text, setText] = useState("Summarize the following for {{audience}}:\n{{body}}"), [model, setModel] = useState(null);
  const New = <Button variant="primary" onClick={() => setOpen(true)}>Create prompt</Button>;
  return (
    <Page title="Prompt management" description="Create, save and version prompts with variables, then use them from your applications and flows.">
      <ResourceTable variant="container" resourceName="Prompts" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="id" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
        filterPlaceholder="Find prompts" empty={{ title: "No prompts", action: New }}
        actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>{New}</SpaceBetween>}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "name", cell: (p) => <Link href={href("bedrock", "prompt-management", p.id)} onFollow={follow}>{p.name}</Link> },
          { id: "id", header: "Prompt ID", cell: (p) => p.id },
          { id: "desc", header: "Description", cell: (p) => p.description || "-" },
          { id: "upd", header: "Last updated", sortingField: "updatedAt", cell: (p) => fmtDate(p.updatedAt) },
        ]} />
      <CreateModal visible={open} onDismiss={() => setOpen(false)} header="Create prompt" submitLabel="Create prompt" disabled={!name || !text}
        onSubmit={async () => {
          const p = await api.createPrompt({ name, defaultVariant: "variant-1", variants: [{ name: "variant-1", templateType: "TEXT", ...(model ? { modelId: model } : {}), templateConfiguration: { text: { text, inputVariables: vars(text).map((n) => ({ name: n })) } } }] });
          notify.success(`Prompt "${name}" created.`); t.reload(); navigate("bedrock", "prompt-management", p.id);
        }}>
        <Field label="Prompt name" constraint="Letters, numbers, hyphens and underscores" value={name} onChange={setName} />
        <FormField label="Prompt template" description="Use {{variable}} for inputs."><Textarea value={text} rows={5} onChange={({ detail }) => setText(detail.value)} ariaLabel="Prompt template" /></FormField>
        <FormField label="Model (optional)"><ModelSelect value={model} onChange={setModel} {...models} /></FormField>
      </CreateModal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="prompt" names={sel.map((p) => p.name)}
        onConfirm={async () => { await api.deletePrompt(sel[0].id); notify.success("Prompt deleted."); setSel([]); t.reload(); }} />
    </Page>
  );
}

export function PromptDetail({ params }) {
  const id = params.id;
  const notify = useNotify();
  const models = useModelOptions();
  const p = useAsync(() => api.getPrompt(id), [id]);
  const vs = useAsync(() => api.listPromptVersions(id), [id]);
  const [text, setText] = useState(null);
  const [model, setModel] = useState(undefined);
  const [vals, setVals] = useState({});
  const [out, setOut] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState("");
  const [del, setDel] = useState(false);
  const d = p.data;
  const v0 = d?.variants?.[0];
  const cur = text ?? v0?.templateConfiguration?.text?.text ?? "";
  const mid = model === undefined ? v0?.modelId : model;
  const save = async () => {
    setBusy("save");
    try {
      const v = { ...v0, ...(mid ? { modelId: mid } : {}), templateConfiguration: { text: { text: cur, inputVariables: vars(cur).map((n) => ({ name: n })) } } };
      await api.updatePrompt(id, { name: d.name, description: d.description, defaultVariant: v.name, variants: [v] });
      notify.success("Draft saved."); setText(null); p.reload();
    } catch (e) { notify.error(e); } finally { setBusy(""); }
  };
  const run = async () => {
    setBusy("run"); setErr(null); setOut(null);
    try {
      let t2 = cur; vars(cur).forEach((k) => { t2 = t2.split(new RegExp(`\\{\\{\\s*${k}\\s*\\}\\}`)).join(vals[k] || ""); });
      const r = await converse(mid, t2);
      setOut(r.output?.message?.content?.map((c) => c.text).join("") || "");
    } catch (e) { setErr(e); } finally { setBusy(""); }
  };
  return (
    <ContentLayout header={<Header variant="h1" actions={<SpaceBetween direction="horizontal" size="xs"><Button onClick={async () => { try { const r = await api.createPromptVersion(id); notify.success(`Version ${r.version} created.`); vs.reload(); } catch (e) { notify.error(e); } }}>Create version</Button><Button onClick={() => setDel(true)}>Delete</Button></SpaceBetween>}>{d?.name || id}</Header>}>
      <SpaceBetween size="l">
        {p.error && <ErrorAlert error={p.error} />}
        {d && <KeyValue title="Prompt overview" items={[["Name", d.name], ["Prompt ID", d.id], ["ARN", d.arn], ["Default variant", d.defaultVariant], ["Version", d.version], ["Last updated", fmtDate(d.updatedAt)]]} />}
        <Container header={<Header variant="h2" actions={<Button loading={busy === "save"} disabled={text === null && model === undefined} onClick={save}>Save draft</Button>}>Prompt builder (working draft)</Header>}>
          <SpaceBetween size="s">
            <FormField label="Prompt template" description="Variables are written {{name}}."><Textarea value={cur} rows={6} onChange={({ detail }) => setText(detail.value)} ariaLabel="Prompt template" /></FormField>
            <FormField label="Model"><ModelSelect value={mid} onChange={setModel} {...models} /></FormField>
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2" description="Fills the variables and runs the prompt through Converse on the selected model.">Test</Header>}>
          <SpaceBetween size="s">
            {vars(cur).map((k) => <FormField key={k} label={k}><Input value={vals[k] || ""} onChange={({ detail }) => setVals({ ...vals, [k]: detail.value })} ariaLabel={`Variable ${k}`} /></FormField>)}
            <Box><Button variant="primary" loading={busy === "run"} disabled={!mid} onClick={run}>Run</Button>{!mid && <Box display="inline" margin={{ left: "s" }} color="text-body-secondary">Choose a model to run the prompt.</Box>}</Box>
            {err && <ErrorAlert error={err} header="Run failed" />}
            {out !== null && <Box data-testid="prompt-output" variant="p">{out}</Box>}
          </SpaceBetween>
        </Container>
        <Table variant="container" header={<Header variant="h2">Versions</Header>} items={(vs.data || []).filter((x) => x.version !== "DRAFT")} trackBy="version" empty={<Box textAlign="center">No versions yet. Create a version to freeze the draft.</Box>}
          columnDefinitions={[{ id: "v", header: "Version", isRowHeader: true, cell: (x) => x.version }, { id: "a", header: "ARN", cell: (x) => x.arn }, { id: "c", header: "Created", cell: (x) => fmtDate(x.updatedAt) }]} />
      </SpaceBetween>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="prompt" names={[d?.name || id]} onConfirm={async () => { await api.deletePrompt(id); notify.success("Prompt deleted."); navigate("bedrock", "prompt-management"); }} />
    </ContentLayout>
  );
}
