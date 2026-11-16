/* DESIGN: visual pipeline modeller (React Flow / xyflow, MIT). Each node edits one stage of the design; Apply writes it to the KB through the real API. */
import { useMemo, useState } from "react";
import { ReactFlow, Background, Controls, Handle, Position, MarkerType } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Textarea from "@cloudscape-design/components/textarea";
import Toggle from "@cloudscape-design/components/toggle";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Alert from "@cloudscape-design/components/alert";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { EMBED_MODELS, PRESETS, applyPreset, designToApi, lintDesign, defaultDesign } from "./engine.js";

const STAGES = [
  ["source", "Source", (d) => `s3://${d.source.bucket}/${d.source.prefix}`],
  ["parse", "Parse", (d) => d.parse.parser],
  ["clean", "Clean / PII scan", (d) => [d.clean.piiScan && "PII scan", d.clean.stripHtml && "strip HTML", d.clean.dedupe && "dedupe"].filter(Boolean).join(", ") || "off"],
  ["chunk", "Chunk", (d) => d.chunk.strategy === "NONE" ? "whole docs" : `${d.chunk.strategy.toLowerCase()} ${d.chunk.maxTokens} tok / ${d.chunk.overlapPct}%`],
  ["embed", "Embed", (d) => EMBED_MODELS[d.embed.model]?.label || d.embed.model],
  ["index", "Index", (d) => d.index.store],
  ["retrieve", "Retrieve", (d) => `${d.retrieve.searchType.toLowerCase()} top-${d.retrieve.topK}${d.retrieve.searchType === "HYBRID" ? ` w=${d.retrieve.hybridWeight}` : ""}${d.retrieve.filterKey ? ` | ${d.retrieve.filterKey}=${d.retrieve.filterValue}` : ""}`],
  ["rerank", "Rerank", (d) => d.rerank.enabled ? `top-${d.rerank.topN}` : "off"],
  ["generate", "Generate", (d) => `grounding >= ${d.generate.groundingThreshold}${d.generate.citations ? " + citations" : ""}`],
];
const SEV = { error: "#d13212", warning: "#f89256", info: "#0972d3" };

function StageNode({ data }) {
  const col = data.sev ? SEV[data.sev] : "#8d99a8";
  return (
    <div data-testid={`node-${data.id}`} style={{ width: 132, padding: "8px 10px", background: "#fff", color: "#0f1b2a", border: `2px solid ${data.selected ? "#0972d3" : col}`, borderRadius: 8, boxShadow: data.selected ? "0 0 0 3px rgba(9,114,211,.25)" : "none", fontSize: 12 }}>
      <Handle type="target" position={Position.Left} /><div style={{ fontWeight: 700 }}>{data.title}{data.sev ? <span style={{ color: col }}> {data.sev === "error" ? "!" : "•"}</span> : null}</div>
      <div style={{ opacity: 0.75, marginTop: 2, wordBreak: "break-word" }}>{data.summary}</div><Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { stage: StageNode };

export default function Design({ design, setDesign, be, ctx, applied, onApply, onIngest, busy, jobMsg, kbKey }) {
  const [sel, setSel] = useState("chunk");
  const [load, setLoad] = useState(false), [text, setText] = useState("");
  const lint = useMemo(() => lintDesign(design, ctx), [design, ctx]);
  const sevOf = (id) => lint.filter((l) => l.node === id).reduce((a, l) => (l.severity === "error" || a === "error" ? "error" : l.severity === "warning" || a === "warning" ? "warning" : "info"), null);
  const nodes = STAGES.map(([id, title, sum], i) => ({ id, type: "stage", position: { x: (i % 5) * 190, y: Math.floor(i / 5) * 120 }, data: { id, title, summary: sum(design), sev: sevOf(id), selected: id === sel }, draggable: true }));
  const edges = STAGES.slice(1).map(([id], i) => ({ id: `e${i}`, source: STAGES[i][0], target: id, markerEnd: { type: MarkerType.ArrowClosed }, animated: id === "retrieve" || id === "generate" }));
  const set = (sec, k) => ({ detail }) => setDesign({ ...design, [sec]: { ...design[sec], [k]: detail.value ?? detail.checked ?? detail.selectedOption?.value } });
  const num = (sec, k) => ({ detail }) => setDesign({ ...design, [sec]: { ...design[sec], [k]: detail.value === "" ? "" : Number(detail.value) } });
  const opt = (a) => a.map((v) => (typeof v === "string" ? { label: v, value: v } : v));
  const sel1 = (sec, k, options) => <Select selectedOption={opt(options).find((o) => o.value === design[sec][k]) || null} onChange={set(sec, k)} options={opt(options)} ariaLabel={`${sec} ${k}`} />;
  const panel = {
    source: <><FormField label="S3 bucket"><Input value={design.source.bucket} onChange={set("source", "bucket")} ariaLabel="bucket" /></FormField><FormField label="Key prefix"><Input value={design.source.prefix} onChange={set("source", "prefix")} ariaLabel="prefix" /></FormField></>,
    parse: <FormField label="Parser">{sel1("parse", "parser", ["text", "layout-aware (PDF/HTML)", "foundation-model"])}</FormField>,
    clean: <SpaceBetween size="s"><Toggle checked={design.clean.piiScan} onChange={set("clean", "piiScan")}>PII scan (flag and exclude)</Toggle><Toggle checked={design.clean.stripHtml} onChange={set("clean", "stripHtml")}>Strip HTML</Toggle><Toggle checked={design.clean.dedupe} onChange={set("clean", "dedupe")}>De-duplicate near-identical chunks</Toggle></SpaceBetween>,
    chunk: <><FormField label="Strategy">{sel1("chunk", "strategy", ["FIXED_SIZE", "SEMANTIC", "HIERARCHICAL", "NONE"])}</FormField><FormField label="Max tokens per chunk"><Input type="number" value={String(design.chunk.maxTokens)} onChange={num("chunk", "maxTokens")} ariaLabel="chunk max tokens" /></FormField><FormField label="Overlap (%)"><Input type="number" value={String(design.chunk.overlapPct)} onChange={num("chunk", "overlapPct")} ariaLabel="chunk overlap" /></FormField></>,
    embed: <FormField label="Embedding model" description={`Window ${EMBED_MODELS[design.embed.model]?.window ?? "?"} tokens`}>{sel1("embed", "model", Object.entries(EMBED_MODELS).map(([value, m]) => ({ value, label: m.label })))}</FormField>,
    index: <FormField label="Vector store">{sel1("index", "store", ["pgvector", "opensearch-serverless", "sqlite-fts5+vectors"])}</FormField>,
    retrieve: <><FormField label="Search type">{sel1("retrieve", "searchType", ["HYBRID", "SEMANTIC"])}</FormField><FormField label="Top-k candidates"><Input type="number" value={String(design.retrieve.topK)} onChange={num("retrieve", "topK")} ariaLabel="top k" /></FormField><FormField label="Hybrid weight (vector share, 0-1)"><Input type="number" value={String(design.retrieve.hybridWeight)} onChange={num("retrieve", "hybridWeight")} ariaLabel="hybrid weight" /></FormField><FormField label="Metadata filter key"><Input value={design.retrieve.filterKey} onChange={set("retrieve", "filterKey")} ariaLabel="filter key" placeholder="department" /></FormField><FormField label="Metadata filter value"><Input value={design.retrieve.filterValue} onChange={set("retrieve", "filterValue")} ariaLabel="filter value" placeholder="hvac" /></FormField></>,
    rerank: <><Toggle checked={design.rerank.enabled} onChange={set("rerank", "enabled")}>Rerank candidates</Toggle><FormField label="Return top N after rerank"><Input type="number" value={String(design.rerank.topN)} onChange={num("rerank", "topN")} ariaLabel="rerank top n" /></FormField></>,
    generate: <><FormField label="Generation model"><Input value={design.generate.model} onChange={set("generate", "model")} ariaLabel="generation model" /></FormField><FormField label="Grounding threshold (0-1)"><Input type="number" value={String(design.generate.groundingThreshold)} onChange={num("generate", "groundingThreshold")} ariaLabel="grounding threshold" /></FormField><Toggle checked={design.generate.citations} onChange={set("generate", "citations")}>Cite sources</Toggle><FormField label="Guardrail"><Input value={design.generate.guardrailId} onChange={set("generate", "guardrailId")} ariaLabel="guardrail" /></FormField></>,
  };
  const save = () => { try { localStorage.setItem(`vyomi.ragstudio.design.${kbKey}`, JSON.stringify(design)); } catch { /* private mode */ } const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(design, null, 2)], { type: "application/json" })); a.download = `${design.name.replace(/\W+/g, "-")}.json`; a.click(); };
  const api = designToApi(design);
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" description="Click a stage to edit its parameters. Red/orange outlines are lint findings (see Validate)."
        actions={<SpaceBetween direction="horizontal" size="xs"><Select selectedOption={null} placeholder="Load preset" onChange={({ detail }) => setDesign(applyPreset(design, detail.selectedOption.value))} options={Object.entries(PRESETS).map(([value, p]) => ({ value, label: p.label, description: p.note }))} ariaLabel="preset" /><Button onClick={() => setDesign(defaultDesign())}>Reset</Button><Button onClick={save} iconName="download">Save JSON</Button><Button onClick={() => { setText(JSON.stringify(design, null, 2)); setLoad(true); }}>Load JSON</Button></SpaceBetween>}>Pipeline modeller</Header>}>
        <div style={{ height: 300 }} data-testid="flow"><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodeClick={(_, n) => setSel(n.id)} fitView fitViewOptions={{ padding: 0.15 }} nodesConnectable={false} proOptions={{ hideAttribution: true }}><Background /><Controls showInteractive={false} /></ReactFlow></div>
      </Container>
      <ColumnLayout columns={2}>
        <Container header={<Header variant="h2">{STAGES.find((s) => s[0] === sel)[1]} parameters</Header>}><SpaceBetween size="s" data-testid="node-params">{panel[sel]}</SpaceBetween></Container>
        <Container header={<Header variant="h2" description="Writes the chunking configuration to the data source (UpdateDataSource) and starts an ingestion job (StartIngestionJob).">Apply to knowledge base</Header>}>
          <SpaceBetween size="s">
            <Box variant="small">Target: <b data-testid="backend-label">{be.label}</b></Box>
            <SpaceBetween direction="horizontal" size="xs"><Button variant="primary" loading={busy === "apply"} onClick={onApply}>Apply design</Button><Button loading={busy === "ingest"} onClick={onIngest}>Apply and ingest</Button></SpaceBetween>
            {jobMsg && <Alert type={jobMsg.type} data-testid="job-msg">{jobMsg.text}</Alert>}
            {applied && <StatusIndicator type="success">Applied chunking: {JSON.stringify(applied)}</StatusIndicator>}
            <ExpandableSection headerText="Real API payload this design produces"><pre style={{ fontSize: 11, maxHeight: 220, overflow: "auto" }} data-testid="api-payload">{JSON.stringify(api, null, 2)}</pre></ExpandableSection>
          </SpaceBetween>
        </Container>
      </ColumnLayout>
      <Modal visible={load} onDismiss={() => setLoad(false)} header="Load design JSON" footer={<Box float="right"><Button variant="primary" onClick={() => { try { setDesign({ ...defaultDesign(), ...JSON.parse(text) }); setLoad(false); } catch (e) { alert("Invalid JSON: " + e.message); } }}>Load</Button></Box>}><Textarea value={text} onChange={({ detail }) => setText(detail.value)} rows={16} ariaLabel="design json" /></Modal>
    </SpaceBetween>
  );
}
