/* DESIGN: the pipeline as stage cards (click to edit), design lint markers, and Apply (PUT index / datasource / skillset / indexer, run indexer). */
import { useMemo, useState } from "react";
import { Input, Select, Switch, Textarea } from "@fluentui/react-components";
import { EMBED_MODELS, PRESETS, applyPreset, lintDesign } from "../../../../common/ragstudio/engine.js";
import { GAPS, NAMES, designToAzure, modeOf } from "./azureMap.js";
import { Alert, Btn, Card, Grid, Label, Pre, Stack, Status } from "./ui.jsx";

const STAGES = [
  ["source", "Source", (d) => `blob: ${d.source.bucket}/${d.source.prefix}`],
  ["clean", "Clean / PII scan", (d) => [d.clean.piiScan && "PII scan", d.clean.stripHtml && "strip HTML", d.clean.dedupe && "dedupe"].filter(Boolean).join(", ") || "off"],
  ["chunk", "Split skill", (d) => d.chunk.strategy === "NONE" ? "whole documents" : `pages ${Math.max(300, d.chunk.maxTokens * 4)} chars / ${d.chunk.overlapPct}%`],
  ["embed", "Embedding skill", (d) => EMBED_MODELS[d.embed.model]?.label || d.embed.model],
  ["index", "Index", () => `${NAMES.index} (vector + text)`],
  ["retrieve", "Query", (d) => { const m = modeOf({ searchType: d.retrieve.searchType, hybridWeight: +d.retrieve.hybridWeight }); return `${m} top-${d.retrieve.topK}${d.retrieve.filterKey ? ` | ${d.retrieve.filterKey}=${d.retrieve.filterValue}` : ""}`; }],
  ["rerank", "Semantic ranker", (d) => d.rerank.enabled ? `top-${d.rerank.topN} (approximation)` : "off"],
  ["generate", "Chat on your data", (d) => `${d.generate.model} | grounding >= ${d.generate.groundingThreshold}`],
];
const SEV = { error: "#d13212", warning: "#c19c00", info: "#0f6cbd" };
const v = (set) => (_, d) => set(d.value);

export default function Design({ design, setDesign, be, ctx, applied, onApply, onIngest, busy, jobMsg, rev, onExport, onImport }) {
  const [sel, setSel] = useState("chunk"), [imp, setImp] = useState(null);
  const lint = useMemo(() => lintDesign(design, ctx), [design, ctx]);
  const sevOf = (id) => lint.filter((l) => l.node === id).reduce((a, l) => (l.severity === "error" || a === "error" ? "error" : l.severity === "warning" || a === "warning" ? "warning" : "info"), null);
  const sec = (s, k, val) => setDesign({ ...design, [s]: { ...design[s], [k]: val } });
  const num = (s, k) => (_, d) => sec(s, k, d.value === "" ? "" : Number(d.value));
  const txt = (s, k) => (_, d) => sec(s, k, d.value);
  const opts = (a) => a.map((x) => <option key={x[0]} value={x[0]}>{x[1]}</option>);
  const panel = {
    source: <><Label label="Blob container" hint="Data source type azureblob (Cosmos DB and Azure SQL sources also exist on the service)."><Input value={design.source.bucket} onChange={txt("source", "bucket")} aria-label="container" /></Label>
      <Label label="Blob folder (prefix)"><Input value={design.source.prefix} onChange={txt("source", "prefix")} aria-label="prefix" /></Label>
      <Label label="Storage account"><Select value={be.env?.storage?.account || ""} onChange={(_, d) => { be.env.storage.account = d.value; setSel("source"); }} aria-label="storage account">{(be.options?.storageAccounts?.length ? be.options.storageAccounts : [be.env?.storage?.account || "(none in this subscription)"]).map((a) => <option key={a}>{a}</option>)}</Select></Label></>,
    clean: <Stack gap={8}>{[["piiScan", "PII scan (flag and exclude)"], ["stripHtml", "Strip HTML"], ["dedupe", "De-duplicate near-identical chunks"]].map(([k, l]) => <Switch key={k} checked={design.clean[k]} onChange={(_, d) => sec("clean", k, d.checked)} label={l} />)}</Stack>,
    chunk: <><Label label="Strategy" hint="Azure splits by pages only: semantic and hierarchical are approximated by pages."><Select value={design.chunk.strategy} onChange={v((x) => sec("chunk", "strategy", x))} aria-label="chunk strategy">{opts(["FIXED_SIZE", "SEMANTIC", "HIERARCHICAL", "NONE"].map((x) => [x, x]))}</Select></Label>
      <Label label="Max tokens per chunk" hint={`SplitSkill maximumPageLength = ${Math.max(300, Math.round(design.chunk.maxTokens * 4))} characters (min 300)`}><Input type="number" value={String(design.chunk.maxTokens)} onChange={num("chunk", "maxTokens")} aria-label="chunk max tokens" /></Label>
      <Label label="Overlap %"><Input type="number" value={String(design.chunk.overlapPct)} onChange={num("chunk", "overlapPct")} aria-label="chunk overlap" /></Label></>,
    embed: <Label label="Embedding model" hint={`AzureOpenAIEmbeddingSkill; vector field dimensions ${EMBED_MODELS[design.embed.model]?.dims ?? "?"}, window ${EMBED_MODELS[design.embed.model]?.window ?? "?"} tokens`}><Select value={design.embed.model} onChange={v((x) => sec("embed", "model", x))} aria-label="embedding model">{opts(Object.entries(EMBED_MODELS).map(([k, m]) => [k, m.label]))}</Select></Label>,
    index: <Alert type="info">One vector index ({NAMES.index}) with chunk, title, parent_id and a vector field (HNSW profile + Azure OpenAI vectorizer), and a semantic configuration. A parent index ({NAMES.parents}) is skipped by index projections.</Alert>,
    retrieve: <><Label label="Search type" hint="HYBRID = keyword + vector (RRF); SEMANTIC = vector only. Vector share 0 = keyword only."><Select value={design.retrieve.searchType} onChange={v((x) => sec("retrieve", "searchType", x))} aria-label="search type">{opts([["HYBRID", "HYBRID (keyword + vector)"], ["SEMANTIC", "SEMANTIC (vector only)"]])}</Select></Label>
      <Label label="Top-k"><Input type="number" value={String(design.retrieve.topK)} onChange={num("retrieve", "topK")} aria-label="top k" /></Label>
      <Label label="Vector share (0 to 1, the vectorQueries weight)"><Input type="number" value={String(design.retrieve.hybridWeight)} onChange={num("retrieve", "hybridWeight")} aria-label="hybrid weight" /></Label>
      <Label label="Filter field" hint="Filterable index field, e.g. title or parent_id"><Input value={design.retrieve.filterKey} onChange={txt("retrieve", "filterKey")} aria-label="filter key" /></Label>
      <Label label="Filter value"><Input value={design.retrieve.filterValue} onChange={txt("retrieve", "filterValue")} aria-label="filter value" /></Label></>,
    rerank: <><Switch checked={design.rerank.enabled} onChange={(_, d) => sec("rerank", "enabled", d.checked)} label="Semantic ranker (queryType semantic)" />
      <Label label="Return top N after rerank"><Input type="number" value={String(design.rerank.topN)} onChange={num("rerank", "topN")} aria-label="rerank top n" /></Label>
      <Alert type="warning">The semantic ranker is an approximation: embedding cosine plus query-term coverage on the 0 to 4 scale, not Microsoft's cross-encoder.</Alert></>,
    generate: <><Label label="Chat deployment (Azure OpenAI)"><Select value={be.env?.aoai?.chatDeployment || ""} onChange={(_, d) => { be.env.aoai.chatDeployment = d.value; setSel("generate"); }} aria-label="chat deployment">{(be.options?.aoai?.flatMap((a) => a.deployments.map((x) => x.name)) || []).concat(be.env?.aoai?.chatDeployment ? [] : ["chat"]).map((x) => <option key={x}>{x}</option>)}{!be.options?.aoai?.length && <option>{be.env?.aoai?.chatDeployment || "chat"}</option>}</Select></Label>
      <Label label="Model label"><Input value={design.generate.model} onChange={txt("generate", "model")} aria-label="generation model" /></Label>
      <Label label="Grounding threshold (0-1)"><Input type="number" value={String(design.generate.groundingThreshold)} onChange={num("generate", "groundingThreshold")} aria-label="grounding threshold" /></Label>
      <Switch checked={design.generate.citations} onChange={(_, d) => sec("generate", "citations", d.checked)} label="Return citations" /></>,
  };
  const spec = useMemo(() => designToAzure(design, be.env), [design, rev, be.env]);
  return (
    <Stack gap={16}>
      <Card title="Pipeline" description="Click a stage to edit it. Red and amber outlines are lint findings (see Validate)."
        actions={<><Select aria-label="preset" value="" onChange={(_, d) => d.value && setDesign(applyPreset(design, d.value))}><option value="">Load preset</option>{Object.entries(PRESETS).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}</Select>
          <Btn onClick={onExport}>Export design</Btn><Btn onClick={() => setImp(imp === null ? "" : null)}>Import design</Btn></>}>
        <div data-testid="flow" style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {STAGES.map(([id, title, sum], i) => {
            const sev = sevOf(id), col = sev ? SEV[sev] : "var(--colorNeutralStroke1, #8d99a8)";
            return <button key={id} data-testid={`node-${id}`} onClick={() => setSel(id)} style={{ width: 150, textAlign: "left", padding: "8px 10px", background: "var(--colorNeutralBackground1, #fff)", color: "inherit", border: `2px solid ${id === sel ? "#0f6cbd" : col}`, borderRadius: 8, cursor: "pointer", font: "inherit", fontSize: 12 }}>
              <div style={{ fontWeight: 700 }}>{i + 1}. {title}{sev && <span style={{ color: col }}> {sev === "error" ? "!" : "•"}</span>}</div><div style={{ opacity: 0.75, marginTop: 2, wordBreak: "break-word" }}>{sum(design)}</div></button>;
          })}
        </div>
        {imp !== null && <Stack gap={8} style={{ marginTop: 12 }}><Textarea value={imp} onChange={(_, d) => setImp(d.value)} rows={8} aria-label="design document json" placeholder='{"schema":"vyomi.rag-design/v1", ...}' />
          <Stack row><Btn primary onClick={() => { if (onImport(imp)) setImp(null); }}>Load document</Btn><Btn onClick={() => setImp(null)}>Cancel</Btn></Stack></Stack>}
      </Card>
      <Grid cols={2}>
        <Card title={`${STAGES.find((s) => s[0] === sel)[1]} parameters`}><Stack gap={10} testid="node-params"><div data-testid="node-params" style={{ display: "flex", flexDirection: "column", gap: 10 }}>{panel[sel]}</div></Stack></Card>
        <Card title="Apply to the search service" description="Recreates the index, skillset and indexer from this design, then (Apply and ingest) runs the indexer: split, embed, project chunks.">
          <Stack gap={10}>
            <div style={{ fontSize: 12 }}>Target: <b data-testid="backend-label">{be.label}</b></div>
            <Stack row><Btn primary disabled={busy !== ""} onClick={onApply}>{busy === "apply" ? "Applying..." : "Apply design"}</Btn><Btn disabled={busy !== ""} onClick={onIngest}>{busy === "ingest" ? "Ingesting..." : "Apply and ingest"}</Btn></Stack>
            {jobMsg && <Alert type={jobMsg.type} data-testid="job-msg">{jobMsg.text}</Alert>}
            {applied && <Status type="success">Applied: {applied}</Status>}
            {spec.notes.map((n) => <Alert key={n} type="warning">{n}.</Alert>)}
            <details><summary>Real API payloads this design produces</summary><Pre testid="api-payload">{JSON.stringify({ skillset: spec.skillset, index: spec.index, indexer: spec.indexer }, null, 2)}</Pre></details>
          </Stack>
        </Card>
      </Grid>
      <Card title="What is approximated on Azure" testid="gaps"><ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>{GAPS.map((g) => <li key={g}>{g}</li>)}</ul></Card>
    </Stack>
  );
}
