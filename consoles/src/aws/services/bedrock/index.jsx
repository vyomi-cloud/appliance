/* Amazon Bedrock: model catalog (ListFoundationModels / GetFoundationModel) + Chat playground (Converse) on core/ai_models_core over the
 * local-LLM seam. Answers come from the small local model the appliance runs - code-path fidelity, not model quality. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Textarea from "@cloudscape-design/components/textarea";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { awsRest } from "../../../common/wire.js";

const R = (m, p, o) => awsRest("bedrock", m, p, o);
const models = () => R("GET", "/foundation-models").then((r) => r.modelSummaries || []);

function Catalog() {
  const t = useAsync(models, []);
  return (
    <ResourceTable resourceName="Foundation models" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="modelId" filterPlaceholder="Filter models"
      empty={{ title: "No models" }}
      columns={[{ id: "n", header: "Model", isRowHeader: true, sortingField: "modelName", cell: (m) => m.modelName }, { id: "p", header: "Provider", sortingField: "providerName", cell: (m) => m.providerName },
        { id: "i", header: "Model ID", cell: (m) => m.modelId }, { id: "in", header: "Input modalities", cell: (m) => m.inputModalities.join(", ") }, { id: "o", header: "Output modalities", cell: (m) => m.outputModalities.join(", ") },
        { id: "s", header: "Streaming", cell: (m) => (m.responseStreamingSupported ? "Supported" : "Not supported") }]} />
  );
}

function Playground() {
  const t = useAsync(models, []);
  const [model, setModel] = useState(null);
  const [system, setSystem] = useState("");
  const [temp, setTemp] = useState("0.5");
  const [maxTok, setMaxTok] = useState("256");
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [meta, setMeta] = useState(null);
  const chat = (t.data || []).filter((m) => m.outputModalities.includes("TEXT"));
  const sel = model || (chat[0] && { label: `${chat[0].providerName} ${chat[0].modelName}`, value: chat[0].modelId });
  const send = async () => {
    const text = input.trim(); if (!text || !sel) return;
    const next = [...msgs, { role: "user", content: [{ text }] }];
    setMsgs(next); setInput(""); setBusy(true); setErr(null);
    try {
      const r = await R("POST", `/model/${encodeURIComponent(sel.value)}/converse`, { body: { messages: next, ...(system ? { system: [{ text: system }] } : {}), inferenceConfig: { temperature: Number(temp), maxTokens: Number(maxTok) } } });
      setMsgs([...next, r.output.message]); setMeta({ usage: r.usage, ms: r.metrics?.latencyMs, stop: r.stopReason });
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <ContentLayout header={<Header variant="h1" description="Converse API">Chat playground</Header>}>
      <SpaceBetween size="l">
        <Alert type="info">Answers are produced by the small local model the appliance runs (not the model you select). It exercises prompting, token accounting and error handling.</Alert>
        <ColumnLayout columns={2}>
          <Container header={<Header variant="h2">Configurations</Header>}><SpaceBetween size="m">
            <FormField label="Model"><Select ariaLabel="Model" selectedOption={sel} options={chat.map((m) => ({ label: `${m.providerName} ${m.modelName}`, value: m.modelId, description: m.modelId }))} onChange={({ detail }) => setModel(detail.selectedOption)} /></FormField>
            <FormField label="System prompt"><Textarea ariaLabel="System prompt" rows={3} value={system} onChange={({ detail }) => setSystem(detail.value)} /></FormField>
            <ColumnLayout columns={2}><FormField label="Temperature"><Input ariaLabel="Temperature" value={temp} onChange={({ detail }) => setTemp(detail.value)} /></FormField>
              <FormField label="Maximum length"><Input ariaLabel="Maximum length" value={maxTok} onChange={({ detail }) => setMaxTok(detail.value)} /></FormField></ColumnLayout>
            {meta && <Box data-testid="bedrock-usage" color="text-body-secondary">Input tokens {meta.usage.inputTokens}, output tokens {meta.usage.outputTokens}, {meta.ms} ms, stop reason: {meta.stop}</Box>}
          </SpaceBetween></Container>
          <Container header={<Header variant="h2" actions={<Button onClick={() => { setMsgs([]); setMeta(null); setErr(null); }}>Reset</Button>}>Chat</Header>}><SpaceBetween size="m">
            <div data-testid="bedrock-log" style={{ minHeight: 160 }}>{msgs.length === 0 ? <Box color="text-body-secondary">Write a prompt to start.</Box> : msgs.map((m, i) => <div key={i}><b>{m.role === "user" ? "You" : "Model"}:</b> {m.content.map((c) => c.text).join("")}</div>)}</div>
            <ErrorAlert error={err} header="The model could not answer" />
            <SpaceBetween direction="horizontal" size="xs"><div style={{ flex: 1, minWidth: 320 }}><Input ariaLabel="Write a prompt" placeholder="Write a prompt" value={input} onChange={({ detail }) => setInput(detail.value)} onKeyDown={({ detail }) => detail.key === "Enter" && send()} /></div>
              <Button variant="primary" loading={busy} onClick={send}>Run</Button></SpaceBetween>
          </SpaceBetween></Container>
        </ColumnLayout>
      </SpaceBetween>
    </ContentLayout>
  );
}

const root = { text: "Amazon Bedrock", href: "#/bedrock" };
export default {
  nav: [{ type: "link", text: "Model catalog", href: "#/bedrock" }, { type: "link", text: "Chat playground", href: "#/bedrock/playground" }],
  routes: [
    { pattern: "/bedrock", component: Catalog, crumbs: () => [root, { text: "Model catalog", href: "#/bedrock" }] },
    { pattern: "/bedrock/playground", component: Playground, crumbs: () => [root, { text: "Chat playground", href: "#/bedrock/playground" }] },
  ],
};
