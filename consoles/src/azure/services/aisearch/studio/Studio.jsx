/* RAG Studio (Azure AI Search): design, validate, test and visualise (pre/post) the knowledge layer of a search service.
 * Live against the simulator's Azure AI Search + Azure OpenAI (+ Vyomi inspect API) or the in-browser demo corpus. Reads/writes vyomi.rag-design/v1. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Tab, TabList } from "@fluentui/react-components";
import { DEFAULT_GOLDEN, DEFAULT_THRESHOLDS, PRESETS, aggregate, applyPreset, corpusStats, lintDesign, retrievalOptions, scoreRow } from "../../../../common/ragstudio/engine.js";
import { fromDocument, toDocument, validate } from "../../../../common/ragstudio/document.js";
import { projectChunks } from "../../../../common/ragstudio/project.js";
import { defaultAzureDesign, designToAzure } from "./azureMap.js";
import { openBackend } from "./backend.js";
import Design from "./Design.jsx";
import Validate from "./Validate.jsx";
import Test, { finalOf } from "./Test.jsx";
import Corpus from "./Corpus.jsx";
import PostRag from "./PostRag.jsx";
import { Alert, Btn, Stack } from "./ui.jsx";

const ls = (k, d) => { try { const x = localStorage.getItem("vyomi.ragstudio.azure." + k); return x ? JSON.parse(x) : d; } catch { return d; } };
const lset = (k, x) => { try { localStorage.setItem("vyomi.ragstudio.azure." + k, JSON.stringify(x)); } catch { /* private mode */ } };
const sig = (spec) => JSON.stringify([spec.skillset, spec.index.fields.map((f) => f.dimensions), spec.datasource.container]);

export default function Studio({ a }) {
  const target = useMemo(() => ({ rg: a?.resourceGroup, name: a?.name }), [a?.resourceGroup, a?.name]);
  const [be, setBe] = useState(null), [rev, setRev] = useState(0), [tab, setTab] = useState("design");
  const [design, setDesign] = useState(() => ls("design", defaultAzureDesign()));
  const [golden, setGolden] = useState(() => ls("golden", DEFAULT_GOLDEN));
  const [runs, setRuns] = useState(() => ls("runs", [])), [thr, setThr] = useState(() => ls("thr", DEFAULT_THRESHOLDS));
  const [data, setData] = useState(null), [dataErr, setDataErr] = useState(null), [proj, setProj] = useState(null), [test, setTest] = useState(null);
  const [busy, setBusy] = useState(""), [jobMsg, setJobMsg] = useState(null), [running, setRunning] = useState(false), [applied, setApplied] = useState(null), [note, setNote] = useState(null);
  const appliedSig = useRef(null);

  const connect = useCallback(async (prefer) => { setBe(null); setData(null); setProj(null); setTest(null); appliedSig.current = null; setBe(await openBackend(prefer, target)); }, [target]);
  useEffect(() => { connect("auto"); }, [connect]);
  useEffect(() => lset("design", design), [design]);
  useEffect(() => lset("golden", golden), [golden]);
  useEffect(() => lset("runs", runs.slice(0, 20)), [runs]);
  useEffect(() => lset("thr", thr), [thr]);

  const loadChunks = useCallback(async (b) => {
    setDataErr(null);
    try { const d = await b.chunks(); setData(d); setProj(projectChunks(d.chunks)); } catch (e) { setData(null); setProj(null); setDataErr(e); }
  }, []);
  useEffect(() => { if (be) loadChunks(be); }, [be, loadChunks]);

  const ctx = useMemo(() => { if (!data) return {}; const st = corpusStats(data.chunks); return { chunks: data.chunks, avgDocTokens: st.avgDocTokens, dupClusters: st.dupClusters.length }; }, [data]);
  const opts = useMemo(() => retrievalOptions(design), [design]);

  const apply = async (d = design, ingest = false) => {
    setBusy(ingest ? "ingest" : "apply"); setJobMsg(null);
    try {
      const spec = designToAzure(d, be.env); await be.applyDesign(spec); appliedSig.current = sig(spec); setApplied(`${spec.skillset.skills[0].textSplitMode} ${spec.skillset.skills[0].maximumPageLength} chars / overlap ${spec.skillset.skills[0].pageOverlapLength}`);
      if (ingest) { const job = await be.ingest(), s = job.statistics || {}; setJobMsg({ type: job.status === "COMPLETE" ? "success" : "error", text: `Indexer run ${job.status}. ${s.numberOfNewDocumentsIndexed ?? 0} documents processed, ${s.numberOfDocumentsFailed ?? 0} failed${s.chunksAfter != null ? `, ${s.chunksAfter} chunks` : ""}.${job.errors?.length ? " " + JSON.stringify(job.errors[0]).slice(0, 200) : ""}` }); await loadChunks(be); }
      else setJobMsg({ type: "success", text: "Design applied (index, skillset and indexer recreated). Run ingestion to split, embed and project the documents." });
    } catch (e) { setJobMsg({ type: "error", text: `${e.code || "Error"}: ${e.message}` }); } finally { setBusy(""); }
  };

  const evaluate = async (which) => {
    setRunning(true);
    try {
      const d = which === "current" ? design : applyPreset(design, which), label = which === "current" ? design.name : PRESETS[which].label;
      const spec = designToAzure(d, be.env);
      if (sig(spec) !== appliedSig.current) { await be.applyDesign(spec); appliedSig.current = sig(spec); await be.ingest(); await loadChunks(be); }   // re-split when the split / embedding config differs
      const o = retrievalOptions(d), k = d.rerank.enabled ? d.rerank.topN : d.retrieve.topK, t0 = performance.now(), rows = [];
      for (const g of golden.filter((x) => x.question)) {
        const [tr, rag] = await Promise.all([be.trace(g.question, o), be.rag(g.question, o).catch(() => ({ output: { text: "" }, citations: [] }))]);
        rows.push({ question: g.question, answer: rag.output?.text || "", scores: scoreRow(g, { retrieved: finalOf(tr), answer: rag.output?.text || "", citations: (rag.citations || []).map((c) => c.uri) }, k) });
      }
      setRuns([{ id: "run" + Date.now(), at: Date.now(), ms: performance.now() - t0, label, design: d, rows, aggregate: aggregate(rows.map((r) => r.scores)) }, ...runs]);
    } catch (e) { setJobMsg({ type: "error", text: `Evaluation failed: ${e.code || ""} ${e.message}` }); } finally { setRunning(false); }
  };

  const onExport = () => {
    const doc = toDocument(design, "azure", { golden, embeddingDimensions: designToAzure(design, be.env).dims }), bad = validate(doc);
    if (bad.length) { setNote({ type: "error", text: `Design document is invalid: ${bad.join("; ")}` }); return; }
    const el = document.createElement("a"); el.href = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" }));
    el.download = `${design.name.replace(/\W+/g, "-").toLowerCase()}.rag-design.json`; document.body.appendChild(el); el.click(); el.remove();
    setNote({ type: "success", text: `Exported ${doc.schema} (cloud azure, ${doc.golden.length} golden questions).` });
  };
  const onImport = (text) => {
    try {
      const doc = JSON.parse(text), bad = validate(doc);
      if (bad.length) { setNote({ type: "error", text: `Not a valid vyomi.rag-design/v1 document: ${bad.slice(0, 3).join("; ")}` }); return false; }
      const r = fromDocument(doc); setDesign(r.design); if (r.golden.length) setGolden(r.golden);
      setNote({ type: "success", text: `Imported "${doc.name}" (designed for ${doc.cloud}). Apply it to build the index.${doc.cloud !== "azure" ? ` Cloud-specific choices (embedding model, store) were kept as written; check Validate.` : ""}` }); return true;
    } catch (e) { setNote({ type: "error", text: `Invalid JSON: ${e.message}` }); return false; }
  };

  if (!be) return <div style={{ padding: 16 }}>Connecting to the search service...</div>;
  const tabs = [["design", "Design"], ["validate", "Validate"], ["test", "Test"], ["corpus", "Corpus (pre-RAG)"], ["post", "Query analysis (post-RAG)"]];
  return (
    <Stack gap={12}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ fontSize: 13, opacity: 0.8, maxWidth: 760 }}>Design, validate and test the retrieval-augmented generation pipeline on this search service (split, embed, index, hybrid query, semantic ranker, chat on your data) with before and after visualisations.</div>
        <Btn onClick={() => connect(be.mode === "fake" ? "auto" : "fake")}>{be.mode === "fake" ? "Try live search service" : "Use demo corpus"}</Btn>
      </div>
      {be.reason && <Alert type="info" data-testid="studio-reason">{be.reason}</Alert>}
      {be.mode === "live-limited" && <Alert type="warning">The search service has no inspect API: Design, Apply, Validate and Test work through the real wires; corpus and stage-score views are limited.</Alert>}
      {note && <Alert type={note.type} data-testid="studio-note">{note.text}</Alert>}
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)}>{tabs.map(([id, l]) => <Tab key={id} value={id} data-testid={`tab-${id}`}>{l}</Tab>)}</TabList>
      {tab === "design" && <Design design={design} setDesign={setDesign} be={be} ctx={ctx} applied={applied} onApply={() => apply(design, false)} onIngest={() => apply(design, true)} busy={busy} jobMsg={jobMsg} rev={rev} onExport={onExport} onImport={onImport} />}
      {tab === "validate" && <Validate design={design} setDesign={setDesign} ctx={ctx} golden={golden} setGolden={setGolden} runs={runs} onRun={evaluate} running={running} thr={thr} setThr={setThr} />}
      {tab === "test" && <Test be={be} design={design} opts={opts} test={test} setTest={setTest} goPost={() => setTab("post")} />}
      {tab === "corpus" && <Corpus data={data} proj={proj} err={dataErr} />}
      {tab === "post" && <PostRag test={test} data={data} proj={proj} runs={runs} thr={thr} />}
    </Stack>
  );
}
