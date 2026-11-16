/* Bedrock Flows: list/create, a visual drag-and-drop canvas (FlowCanvas, xyflow) with Prompt / Condition / Agent / KnowledgeBase / Lambda /
 * Iterator / Collector / Loop / Retrieval / Storage nodes, a JSON tab, Prepare, versions, aliases and Test (InvokeFlow on TSTALIASID with
 * execution tracing). Runner: core/bedrock_build_core._Run. */
import { useMemo, useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import Tabs from "@cloudscape-design/components/tabs";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import { CapabilityContainer } from "../../../kit/Capability.jsx";
import FlowCanvas from "./FlowCanvas.jsx";
import DeleteModal from "../../../kit/DeleteModal.jsx";
import { ErrorAlert, KeyValue, fmtDate } from "../../../kit/common.jsx";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import { follow, href, navigate } from "../../../../common/router.js";
import { CreateModal, Field, ModelSelect, Page, useModelOptions } from "../inferTune/Shared.jsx";
import { NOVA } from "../Common.jsx";
import * as api from "./api.js";
import * as base from "../api.js";

const data = (name, source, target, so, ti) => ({ name, type: "Data", source, target, configuration: { data: { sourceOutput: so, targetInput: ti } } });
/** The console's starter: Input -> Prompt -> Output. */
export const starterFlow = (modelId, template) => ({
  nodes: [
    { name: "FlowInputNode", type: "Input", configuration: { input: {} }, outputs: [{ name: "document", type: "String" }] },
    { name: "Prompt_1", type: "Prompt", configuration: { prompt: { sourceConfiguration: { inline: { modelId, templateType: "TEXT", templateConfiguration: { text: { text: template, inputVariables: [{ name: "input" }] } }, inferenceConfiguration: { text: { temperature: 0.2 } } } } } },
      inputs: [{ name: "input", type: "String", expression: "$.data" }], outputs: [{ name: "modelCompletion", type: "String" }] },
    { name: "FlowOutputNode", type: "Output", configuration: { output: {} }, inputs: [{ name: "document", type: "String", expression: "$.data" }] },
  ],
  connections: [data("FlowInputNodeToPrompt_1", "FlowInputNode", "Prompt_1", "document", "input"), data("Prompt_1ToFlowOutputNode", "Prompt_1", "FlowOutputNode", "modelCompletion", "document")],
});

const flowStatus = (s) => <StatusIndicator type={s === "Prepared" ? "success" : "pending"}>{s}</StatusIndicator>;

export function Flows() {
  const t = useAsync(() => api.listFlows(), []);
  const models = useModelOptions();
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false);
  const [del, setDel] = useState(false);
  const [name, setName] = useState(""), [model, setModel] = useState(NOVA), [tpl, setTpl] = useState("{{input}}");
  const New = <Button variant="primary" onClick={() => setOpen(true)}>Create flow</Button>;
  return (
    <Page title="Flows" description="Build generative AI workflows by linking prompts, conditions and outputs. Test with a sample input, then version and alias the flow.">
      <ResourceTable variant="container" resourceName="Flows" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="id" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
        filterPlaceholder="Find flows" empty={{ title: "No flows", action: New }}
        actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>{New}</SpaceBetween>}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "name", cell: (f) => <Link href={href("bedrock", "flows", f.id)} onFollow={follow}>{f.name}</Link> },
          { id: "id", header: "Flow ID", cell: (f) => f.id },
          { id: "st", header: "Status", cell: (f) => flowStatus(f.status) },
          { id: "upd", header: "Last updated", sortingField: "updatedAt", cell: (f) => fmtDate(f.updatedAt) },
        ]} />
      <CreateModal visible={open} onDismiss={() => setOpen(false)} header="Create flow" submitLabel="Create flow" disabled={!name || !model}
        onSubmit={async () => { const f = await api.createFlow({ name, definition: starterFlow(model, tpl) }); notify.success(`Flow "${name}" created.`); t.reload(); navigate("bedrock", "flows", f.id); }}>
        <Field label="Flow name" constraint="Letters, numbers, hyphens and underscores" value={name} onChange={setName} />
        <FormField label="Model for the Prompt node"><ModelSelect value={model} onChange={setModel} {...models} /></FormField>
        <FormField label="Prompt template" description="{{input}} receives the flow input."><Textarea value={tpl} rows={3} onChange={({ detail }) => setTpl(detail.value)} ariaLabel="Prompt template" /></FormField>
      </CreateModal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="flow" names={sel.map((f) => f.name)}
        onConfirm={async () => { await api.deleteFlow(sel[0].id); notify.success("Flow deleted."); setSel([]); t.reload(); }} />
    </Page>
  );
}

export function FlowDetail({ params }) {
  const id = params.id;
  const notify = useNotify();
  const f = useAsync(() => api.getFlow(id), [id]);
  const vs = useAsync(() => api.listFlowVersions(id), [id]);
  const as = useAsync(() => api.listFlowAliases(id), [id]);
  const [json, setJson] = useState(null);
  const [input, setInput] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState("");
  const [del, setDel] = useState(false);
  const [aliasName, setAliasName] = useState("");
  const [draft, setDraft] = useState(null);       // definition from the canvas (null until the user touches it)
  const [runStates, setRunStates] = useState({});
  const models = useModelOptions();
  const refs = useAsync(async () => {
    const safe = (p) => p.catch(() => []);
    const [kbs, lambdas, buckets, agents] = await Promise.all([safe(base.listKnowledgeBases()), safe(base.listLambdas()), safe(base.listBuckets()), safe(base.listAgents())]);
    const aliases = (await Promise.all(agents.map((a) => safe(base.listAliases(a.agentId)).then((as) => as.map((x) => ({ value: `arn:aws:bedrock:us-east-1:${base.ACCOUNT}:agent-alias/${a.agentId}/${x.agentAliasId}`, label: `${a.agentName} / ${x.agentAliasName}` })))))).flat();
    return { kbs: kbs.map((k) => ({ value: k.knowledgeBaseId, label: k.name })), lambdas: lambdas.map((l) => ({ value: l.arn, label: l.name })), buckets: buckets.map((b) => ({ value: b, label: b })), aliases };
  }, []);
  const opts = { models: models.options.map((m) => ({ value: m.value, label: m.label })), ...(refs.data || { kbs: [], lambdas: [], buckets: [], aliases: [] }) };
  const d = f.data;
  const cur = json ?? (d ? JSON.stringify(d.definition, null, 2) : "");
  const canvasDef = draft || d?.definition;
  const dirty = draft && JSON.stringify(draft) !== JSON.stringify(d?.definition);
  const run = async (key, fn, ok) => { setBusy(key); try { await fn(); if (ok) notify.success(ok); f.reload(); vs.reload(); as.reload(); } catch (e) { notify.error(e); } finally { setBusy(""); } };
  const save = () => run("save", async () => { await api.updateFlow(id, { name: d.name, executionRoleArn: d.executionRoleArn, definition: json !== null ? JSON.parse(cur) : draft }); setJson(null); setDraft(null); }, "Flow saved (prepare it before testing).");
  const test = async () => {
    setBusy("test"); setErr(null); setRes(null); setRunStates({});
    try {
      const r = await api.invokeFlow(id, input, "TSTALIASID", true);
      setRes(r);
      const ok = {};
      r.trace.forEach((t) => { const n = t.nodeOutputTrace?.nodeName || t.nodeInputTrace?.nodeName || t.conditionNodeResultTrace?.nodeName; if (n) ok[n] = "ok"; });
      r.outputs.forEach((o) => { ok[o.nodeName] = "ok"; });
      setRunStates(ok);
    } catch (e) { setErr(e); } finally { setBusy(""); }
  };
  const traceRows = (res?.trace || []).map((t, i) => {
    const k = Object.keys(t)[0], v = t[k];
    const fields = v.fields ? v.fields.map((x) => `${x.nodeInputName || x.nodeOutputName}=${typeof x.content?.document === "string" ? x.content.document : JSON.stringify(x.content?.document)}`).join("; ") : (v.satisfiedConditions || []).map((c) => c.conditionName).join(", ") || "none";
    return { i: i + 1, node: v.nodeName, kind: k === "nodeInputTrace" ? "Input" : k === "nodeOutputTrace" ? "Output" : "Condition result", fields, at: v.timestamp };
  });
  
  return (
    <ContentLayout header={<Header variant="h1" actions={<SpaceBetween direction="horizontal" size="xs"><Button loading={busy === "prep"} onClick={() => run("prep", () => api.prepareFlow(id), "Flow prepared.")}>Prepare</Button><Button onClick={() => setDel(true)}>Delete</Button></SpaceBetween>}>{d?.name || id}</Header>}>
      <SpaceBetween size="l">
        {f.error && <ErrorAlert error={f.error} />}
        {d && <KeyValue title="Flow overview" items={[["Name", d.name], ["Flow ID", d.id], ["Status", flowStatus(d.status)], ["ARN", d.arn], ["Execution role", d.executionRoleArn], ["Last updated", fmtDate(d.updatedAt)]]} />}
        <CapabilityContainer id="bedrock.flows" title="Flow builder" description="Drag nodes from the palette, connect output ports to input ports, then save and prepare."
          actions={<SpaceBetween direction="horizontal" size="xs"><Button loading={busy === "save"} disabled={!dirty && json === null} onClick={save}>Save</Button></SpaceBetween>}>
          {d && <Tabs tabs={[
            { id: "canvas", label: "Canvas", content: <FlowCanvas key={`${id}:${d.updatedAt}`} initial={d.definition} onChange={setDraft} layoutKey={`vyomi.flowlayout.${id}`} opts={opts} runStates={runStates} /> },
            { id: "def", label: "Definition (JSON)", content: <SpaceBetween size="s"><Textarea value={cur} rows={16} onChange={({ detail }) => setJson(detail.value)} ariaLabel="Flow definition" />
              <Box color="text-body-secondary" variant="small">Raw CreateFlow/UpdateFlow definition. Node types: Input, Output, Prompt, Condition, Collector, Iterator, Agent, KnowledgeBase, LambdaFunction, Retrieval, Storage, Loop. Lex and InlineCode are not supported. Save from the button above.</Box></SpaceBetween> },
          ]} />}
        </CapabilityContainer>
        <Container header={<Header variant="h2" description="Runs the prepared working draft (test alias TSTALIASID) through InvokeFlow.">Test flow</Header>}>
          <SpaceBetween size="s">
            {d && d.status !== "Prepared" && <Box color="text-status-warning">Prepare the flow before testing it.</Box>}
            <FormField label="Input" description="Text, or a JSON array such as [1,2,3] for flows that start with an Iterator."><Textarea value={input} rows={3} onChange={({ detail }) => setInput(detail.value)} ariaLabel="Flow input" placeholder="Text sent to the input node" /></FormField>
            <Box><Button variant="primary" loading={busy === "test"} disabled={!input || d?.status !== "Prepared"} onClick={test}>Run</Button></Box>
            {err && <ErrorAlert error={err} header="Flow failed" />}
            {res && <div data-testid="flow-result"><SpaceBetween size="xs">{res.outputs.map((o, i) => <Box key={i}><b>{o.nodeName}</b>: {typeof o.content?.document === "string" ? o.content.document : JSON.stringify(o.content?.document)}</Box>)}<Box color="text-body-secondary">Completion: {res.reason}</Box></SpaceBetween></div>}
            {res && <Table variant="embedded" header={<Header variant="h3" counter={`(${traceRows.length})`}>Execution trace</Header>} items={traceRows} trackBy="i" empty={<Box textAlign="center">No trace events</Box>}
              columnDefinitions={[{ id: "i", header: "#", cell: (r) => r.i }, { id: "n", header: "Node", cell: (r) => r.node }, { id: "k", header: "Event", cell: (r) => r.kind }, { id: "f", header: "Values", cell: (r) => <span data-testid="trace-values">{r.fields}</span> }]} />}
          </SpaceBetween>
        </Container>
        <Table variant="container" header={<Header variant="h2" actions={<Button loading={busy === "ver"} disabled={d?.status !== "Prepared"} onClick={() => run("ver", () => api.createFlowVersion(id), "Version created.")}>Publish version</Button>}>Versions</Header>}
          items={vs.data || []} trackBy="version" empty={<Box textAlign="center">No versions</Box>}
          columnDefinitions={[{ id: "v", header: "Version", isRowHeader: true, cell: (x) => x.version }, { id: "a", header: "ARN", cell: (x) => x.arn }, { id: "c", header: "Created", cell: (x) => fmtDate(x.createdAt) }]} />
        <Table variant="container" header={<Header variant="h2">Aliases</Header>} items={as.data || []} trackBy="id" empty={<Box textAlign="center">No aliases</Box>}
          columnDefinitions={[{ id: "n", header: "Alias", isRowHeader: true, cell: (x) => x.name }, { id: "i", header: "Alias ID", cell: (x) => x.id }, { id: "v", header: "Version", cell: (x) => x.routingConfiguration?.[0]?.flowVersion },
            { id: "x", header: "", cell: (x) => <Button variant="inline-link" onClick={() => run("dal", () => api.deleteFlowAlias(id, x.id), "Alias deleted.")}>Delete</Button> }]}
          filter={<SpaceBetween direction="horizontal" size="xs"><Field label="" placeholder="alias name" value={aliasName} onChange={setAliasName} /><Button disabled={!aliasName || !(vs.data || []).length} onClick={() => run("al", async () => { const v = vs.data[vs.data.length - 1].version; await api.createFlowAlias(id, aliasName, v); setAliasName(""); }, "Alias created on the latest version.")}>Create alias</Button></SpaceBetween>} />
      </SpaceBetween>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="flow" names={[d?.name || id]} onConfirm={async () => { await api.deleteFlow(id); notify.success("Flow deleted."); navigate("bedrock", "flows"); }} />
    </ContentLayout>
  );
}
