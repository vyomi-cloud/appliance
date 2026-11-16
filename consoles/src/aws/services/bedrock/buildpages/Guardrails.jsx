/* Bedrock Guardrails: list, create/edit wizard (content, topics, words, PII, grounding), versions and the Test panel (ApplyGuardrail)
 * over core/bedrock_guardrails_core.py. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import Multiselect from "@cloudscape-design/components/multiselect";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import FormField from "@cloudscape-design/components/form-field";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import DeleteModal from "../../../kit/DeleteModal.jsx";
import { ErrorAlert, KeyValue, fmtDate } from "../../../kit/common.jsx";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import { follow, href, navigate } from "../../../../common/router.js";
import { CreateModal, Field, Page } from "../inferTune/Shared.jsx";
import * as api from "./api.js";

const FILTERS = ["HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT", "PROMPT_ATTACK"];
const STRENGTH = ["NONE", "LOW", "MEDIUM", "HIGH"].map((v) => ({ label: v === "NONE" ? "None" : v[0] + v.slice(1).toLowerCase(), value: v }));
const PII = ["EMAIL", "PHONE", "NAME", "ADDRESS", "AGE", "US_SOCIAL_SECURITY_NUMBER", "CREDIT_DEBIT_CARD_NUMBER", "IP_ADDRESS", "URL", "AWS_ACCESS_KEY", "AWS_SECRET_KEY", "PASSWORD", "USERNAME", "PIN"];
const PII_ACTIONS = ["BLOCK", "ANONYMIZE"].map((v) => ({ label: v === "BLOCK" ? "Block" : "Mask", value: v }));
const opt = (list, v) => list.find((o) => o.value === v) || list[0];

/** Console form state <-> CreateGuardrail request. */
function toForm(g) {
  const f = { name: g?.name || "", description: g?.description || "", blockedIn: g?.blockedInputMessaging || "Sorry, the model cannot answer this question.", blockedOut: g?.blockedOutputsMessaging || "Sorry, the model cannot answer this question.",
    filters: Object.fromEntries(FILTERS.map((t) => [t, "NONE"])), topics: (g?.topicPolicy?.topics || []).map((t) => ({ name: t.name, definition: t.definition })), words: (g?.wordPolicy?.words || []).map((w) => w.text).join(", "),
    profanity: !!(g?.wordPolicy?.managedWordLists || []).length, pii: Object.fromEntries((g?.sensitiveInformationPolicy?.piiEntities || []).map((e) => [e.type, e.action])),
    regexes: (g?.sensitiveInformationPolicy?.regexes || []).map((r) => `${r.name}=${r.pattern}`).join("\n"), grounding: 0, relevance: 0 };
  (g?.contentPolicy?.filters || []).forEach((x) => { f.filters[x.type] = x.inputStrength; });
  (g?.contextualGroundingPolicy?.filters || []).forEach((x) => { if (x.type === "GROUNDING") f.grounding = x.threshold; else f.relevance = x.threshold; });
  return f;
}
function toRequest(f) {
  const r = { name: f.name, description: f.description || undefined, blockedInputMessaging: f.blockedIn, blockedOutputsMessaging: f.blockedOut };
  const cf = FILTERS.filter((t) => f.filters[t] !== "NONE").map((t) => ({ type: t, inputStrength: f.filters[t], outputStrength: t === "PROMPT_ATTACK" ? "NONE" : f.filters[t] }));
  if (cf.length) r.contentPolicyConfig = { filtersConfig: cf };
  const tp = f.topics.filter((t) => t.name && t.definition).map((t) => ({ name: t.name, definition: t.definition, type: "DENY" }));
  if (tp.length) r.topicPolicyConfig = { topicsConfig: tp };
  const words = f.words.split(",").map((w) => w.trim()).filter(Boolean);
  if (words.length || f.profanity) r.wordPolicyConfig = { ...(words.length ? { wordsConfig: words.map((text) => ({ text })) } : {}), ...(f.profanity ? { managedWordListsConfig: [{ type: "PROFANITY" }] } : {}) };
  const pii = Object.entries(f.pii).map(([type, action]) => ({ type, action }));
  const rx = f.regexes.split("\n").map((l) => l.trim()).filter((l) => l.includes("=")).map((l) => { const i = l.indexOf("="); return { name: l.slice(0, i), pattern: l.slice(i + 1), action: "BLOCK" }; });
  if (pii.length || rx.length) r.sensitiveInformationPolicyConfig = { ...(pii.length ? { piiEntitiesConfig: pii } : {}), ...(rx.length ? { regexesConfig: rx } : {}) };
  const gf = [["GROUNDING", f.grounding], ["RELEVANCE", f.relevance]].filter(([, v]) => Number(v) > 0).map(([type, v]) => ({ type, threshold: Number(v) }));
  if (gf.length) r.contextualGroundingPolicyConfig = { filtersConfig: gf };
  return r;
}

function GuardrailForm({ visible, onDismiss, existing, onSaved }) {
  const [f, setF] = useState(() => toForm(existing));
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  const notify = useNotify();
  const sensible = f.name && f.blockedIn && f.blockedOut;
  return (
    <CreateModal visible={visible} onDismiss={onDismiss} size="large" header={existing ? "Edit guardrail" : "Create guardrail"} submitLabel={existing ? "Save" : "Create guardrail"} disabled={!sensible}
      onSubmit={async () => { const r = toRequest(f); const out = existing ? await api.updateGuardrail(existing.guardrailId, r) : await api.createGuardrail(r); notify.success(`Guardrail "${f.name}" ${existing ? "updated" : "created"}.`); onSaved(out); }}>
      <Field label="Name" value={f.name} onChange={(v) => set("name", v)} />
      <Field label="Description" value={f.description} onChange={(v) => set("description", v)} />
      <Field label="Messaging for blocked prompts" value={f.blockedIn} onChange={(v) => set("blockedIn", v)} />
      <Field label="Messaging for blocked responses" value={f.blockedOut} onChange={(v) => set("blockedOut", v)} />
      <Tabs tabs={[
        { id: "content", label: "Content filters", content: (
          <SpaceBetween size="s">
            <Box color="text-body-secondary">Strength applies to prompts and responses (Prompt attacks apply to prompts only). Matching uses the simulator's lexicon, not the managed classifier.</Box>
            {FILTERS.map((t) => (
              <FormField key={t} label={t[0] + t.slice(1).toLowerCase().replace("_", " ")}>
                <Select selectedOption={opt(STRENGTH, f.filters[t])} options={STRENGTH} onChange={({ detail }) => set("filters", { ...f.filters, [t]: detail.selectedOption.value })} ariaLabel={`${t} strength`} />
              </FormField>))}
          </SpaceBetween>) },
        { id: "topics", label: "Denied topics", content: (
          <SpaceBetween size="s">
            {f.topics.map((t, i) => (
              <SpaceBetween size="xxs" key={i}>
                <Field label={`Topic ${i + 1} name`} value={t.name} onChange={(v) => set("topics", f.topics.map((x, j) => (j === i ? { ...x, name: v } : x)))} />
                <Field label="Definition" value={t.definition} onChange={(v) => set("topics", f.topics.map((x, j) => (j === i ? { ...x, definition: v } : x)))} />
                <Button variant="inline-link" onClick={() => set("topics", f.topics.filter((_, j) => j !== i))}>Remove topic</Button>
              </SpaceBetween>))}
            <Button onClick={() => set("topics", [...f.topics, { name: "", definition: "" }])}>Add denied topic</Button>
          </SpaceBetween>) },
        { id: "words", label: "Word filters", content: (
          <SpaceBetween size="s">
            <FormField label="Custom words and phrases" description="Comma separated; matched case-insensitively."><Textarea value={f.words} rows={3} onChange={({ detail }) => set("words", detail.value)} ariaLabel="Words" /></FormField>
            <Button variant={f.profanity ? "primary" : "normal"} iconName={f.profanity ? "status-positive" : undefined} onClick={() => set("profanity", !f.profanity)}>Filter profanity (managed list)</Button>
          </SpaceBetween>) },
        { id: "pii", label: "Sensitive information", content: (
          <SpaceBetween size="s">
            <FormField label="PII types"><Multiselect selectedOptions={Object.keys(f.pii).map((v) => ({ label: v, value: v }))} options={PII.map((v) => ({ label: v, value: v }))} placeholder="Choose PII types"
              onChange={({ detail }) => set("pii", Object.fromEntries(detail.selectedOptions.map((o) => [o.value, f.pii[o.value] || "BLOCK"])))} ariaLabel="PII types" /></FormField>
            {Object.keys(f.pii).map((t) => (
              <FormField key={t} label={`${t} action`}><Select selectedOption={opt(PII_ACTIONS, f.pii[t])} options={PII_ACTIONS} onChange={({ detail }) => set("pii", { ...f.pii, [t]: detail.selectedOption.value })} ariaLabel={`${t} action`} /></FormField>))}
            <FormField label="Regex patterns" description="One per line: name=pattern"><Textarea value={f.regexes} rows={3} onChange={({ detail }) => set("regexes", detail.value)} ariaLabel="Regex patterns" /></FormField>
          </SpaceBetween>) },
        { id: "grounding", label: "Contextual grounding", content: (
          <SpaceBetween size="s">
            <Field label="Grounding threshold (0 disables, max 0.99)" type="number" value={String(f.grounding)} onChange={(v) => set("grounding", v)} />
            <Field label="Relevance threshold (0 disables, max 0.99)" type="number" value={String(f.relevance)} onChange={(v) => set("relevance", v)} />
          </SpaceBetween>) },
      ]} />
    </CreateModal>
  );
}

export function Guardrails() {
  const t = useAsync(() => api.listGuardrails(), []);
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const New = <Button variant="primary" onClick={() => setCreate(true)}>Create guardrail</Button>;
  return (
    <Page title="Guardrails" description="Implement safeguards for your generative AI applications: content filters, denied topics, word filters, sensitive information filters and contextual grounding checks.">
      <ResourceTable variant="container" resourceName="Guardrails" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="id" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
        filterPlaceholder="Find guardrails" empty={{ title: "No guardrails", action: New }}
        actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>{New}</SpaceBetween>}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "name", cell: (g) => <Link href={href("bedrock", "guardrails", g.id)} onFollow={follow}>{g.name}</Link> },
          { id: "id", header: "Guardrail ID", cell: (g) => g.id },
          { id: "status", header: "Status", cell: (g) => <StatusIndicator type="success">{g.status === "READY" ? "Ready" : g.status}</StatusIndicator> },
          { id: "ver", header: "Working draft", cell: () => "DRAFT" },
          { id: "upd", header: "Last updated", cell: (g) => fmtDate(g.updatedAt) },
        ]} />
      {create && <GuardrailForm visible onDismiss={() => setCreate(false)} onSaved={(o) => { t.reload(); navigate("bedrock", "guardrails", o.guardrailId); }} />}
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="guardrail" names={sel.map((g) => g.name)}
        onConfirm={async () => { await api.deleteGuardrail(sel[0].id); notify.success("Guardrail deleted."); setSel([]); t.reload(); }} />
    </Page>
  );
}

const pretty = (o) => JSON.stringify(o, null, 2);

export function GuardrailDetail({ params }) {
  const id = params.id;
  const notify = useNotify();
  const g = useAsync(() => api.getGuardrail(id), [id]);
  const vs = useAsync(() => api.listGuardrailVersions(id), [id]);
  const [edit, setEdit] = useState(false);
  const [del, setDel] = useState(false);
  const [ver, setVer] = useState("DRAFT");
  const [source, setSource] = useState("INPUT");
  const [text, setText] = useState("");
  const [ground, setGround] = useState("");
  const [query, setQuery] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const d = g.data;
  const verOpts = (vs.data || []).map((v) => ({ label: v.version === "DRAFT" ? "Working draft (DRAFT)" : `Version ${v.version}`, value: v.version }));
  const test = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      const content = [{ text: { text } }];
      if (source === "OUTPUT" && ground) content.unshift({ text: { text: ground, qualifiers: ["grounding_source"] } });
      if (source === "OUTPUT" && query) content.unshift({ text: { text: query, qualifiers: ["query"] } });
      setRes(await api.applyGuardrail(id, ver, source, content));
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const policies = d && [["Content filters", d.contentPolicy?.filters?.map((f) => `${f.type}: in ${f.inputStrength} / out ${f.outputStrength}`)],
    ["Denied topics", d.topicPolicy?.topics?.map((t) => `${t.name}: ${t.definition}`)], ["Word filters", [...(d.wordPolicy?.words || []).map((w) => w.text), ...(d.wordPolicy?.managedWordLists || []).map((m) => `managed: ${m.type}`)]],
    ["Sensitive information", [...(d.sensitiveInformationPolicy?.piiEntities || []).map((e) => `${e.type}: ${e.action}`), ...(d.sensitiveInformationPolicy?.regexes || []).map((r) => `regex ${r.name}`)]],
    ["Contextual grounding", d.contextualGroundingPolicy?.filters?.map((f) => `${f.type} >= ${f.threshold}`)]];
  return (
    <ContentLayout header={<Header variant="h1" actions={<SpaceBetween direction="horizontal" size="xs"><Button onClick={() => setEdit(true)}>Edit</Button><Button onClick={() => setDel(true)}>Delete</Button></SpaceBetween>}>{d?.name || id}</Header>}>
      <SpaceBetween size="l">
        {g.error && <ErrorAlert error={g.error} />}
        {d && <KeyValue title="Guardrail overview" columns={3} items={[["Name", d.name], ["Status", <StatusIndicator type="success">Ready</StatusIndicator>], ["Guardrail ID", d.guardrailId], ["ARN", d.guardrailArn], ["Description", d.description],
          ["Blocked prompt message", d.blockedInputMessaging], ["Blocked response message", d.blockedOutputsMessaging], ["Last updated", fmtDate(d.updatedAt)]]} />}
        <Container header={<Header variant="h2">Test</Header>}>
          <SpaceBetween size="s">
            <Alert type="info">Runs ApplyGuardrail against the selected version. Checks use the simulator's lexicon and regex engine plus a local-model grounding score; they are not the managed classifiers.</Alert>
            <SpaceBetween direction="horizontal" size="xs">
              <Select selectedOption={opt(verOpts.length ? verOpts : [{ label: "Working draft (DRAFT)", value: "DRAFT" }], ver)} options={verOpts} onChange={({ detail }) => setVer(detail.selectedOption.value)} ariaLabel="Guardrail version" />
              <Select selectedOption={{ label: source === "INPUT" ? "Prompt (input)" : "Model response (output)", value: source }} options={[{ label: "Prompt (input)", value: "INPUT" }, { label: "Model response (output)", value: "OUTPUT" }]} onChange={({ detail }) => setSource(detail.selectedOption.value)} ariaLabel="Source" />
            </SpaceBetween>
            {source === "OUTPUT" && <><FormField label="Grounding source (optional)"><Textarea value={ground} rows={2} onChange={({ detail }) => setGround(detail.value)} ariaLabel="Grounding source" /></FormField>
              <FormField label="Query (optional)"><Textarea value={query} rows={1} onChange={({ detail }) => setQuery(detail.value)} ariaLabel="Query" /></FormField></>}
            <FormField label={source === "INPUT" ? "Prompt" : "Model response"}><Textarea value={text} rows={4} onChange={({ detail }) => setText(detail.value)} ariaLabel="Test text" placeholder="Enter text to test against the guardrail" /></FormField>
            <Box><Button variant="primary" loading={busy} disabled={!text} onClick={test}>Test guardrail</Button></Box>
            {err && <ErrorAlert error={err} header="Test failed" />}
            {res && <div data-testid="guardrail-result"><SpaceBetween size="xs">
              <StatusIndicator type={res.action === "NONE" ? "success" : "warning"}>{res.action === "NONE" ? "No intervention: the guardrail let the content through" : "Guardrail intervened"}</StatusIndicator>
              {res.outputs?.map((o, i) => <Box key={i}>Final text: <b>{o.text}</b></Box>)}
              <Box variant="awsui-key-label">Assessments</Box><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{pretty(res.assessments)}</pre>
            </SpaceBetween></div>}
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2">Configured policies</Header>}>
          <SpaceBetween size="xs">{(policies || []).map(([k, v]) => <div key={k}><Box variant="awsui-key-label">{k}</Box>{v?.length ? v.map((x) => <div key={x}>{x}</div>) : <Box color="text-body-secondary">Not configured</Box>}</div>)}</SpaceBetween>
        </Container>
        <Table variant="container" header={<Header variant="h2" actions={<Button onClick={async () => { try { const r = await api.createGuardrailVersion(id); notify.success(`Version ${r.version} created.`); vs.reload(); } catch (e) { notify.error(e); } }}>Create version</Button>}>Versions</Header>}
          items={vs.data || []} trackBy="version" empty={<Box textAlign="center">No versions yet</Box>}
          columnDefinitions={[{ id: "v", header: "Version", isRowHeader: true, cell: (x) => x.version }, { id: "d", header: "Description", cell: (x) => x.description || "-" }, { id: "c", header: "Created", cell: (x) => fmtDate(x.createdAt) }]} />
      </SpaceBetween>
      {edit && d && <GuardrailForm visible existing={d} onDismiss={() => setEdit(false)} onSaved={() => { g.reload(); }} />}
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="guardrail" names={[d?.name || id]} onConfirm={async () => { await api.deleteGuardrail(id); notify.success("Guardrail deleted."); navigate("bedrock", "guardrails"); }} />
    </ContentLayout>
  );
}
