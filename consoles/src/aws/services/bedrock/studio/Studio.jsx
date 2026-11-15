/* RAG Studio: design, validate, test and visualise (pre/post) the knowledge layer of facilities-kb.
 * Works against the live bedrock-agent / bedrock-agent-runtime wires (+ Vyomi inspect API) or an in-browser demo corpus. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tabs from "@cloudscape-design/components/tabs";
import { openBackend } from "./backend.js";
import { DEFAULT_GOLDEN, DEFAULT_THRESHOLDS, PRESETS, aggregate, applyPreset, corpusStats, defaultDesign, designToApi, retrievalOptions, scoreRow } from "./engine.js";
import { projectChunks } from "./project.js";
import Design from "./Design.jsx";
import Validate from "./Validate.jsx";
import Test, { finalOf } from "./Test.jsx";
import Corpus from "./Corpus.jsx";
import PostRag from "./PostRag.jsx";

const ls = (k, d) => { try { const v = localStorage.getItem("vyomi.ragstudio." + k); return v ? JSON.parse(v) : d; } catch { return d; } };
const lset = (k, v) => { try { localStorage.setItem("vyomi.ragstudio." + k, JSON.stringify(v)); } catch { /* private mode */ } };
const sig = (d) => JSON.stringify(designToApi(d).dataSource.vectorIngestionConfiguration);

export default function Studio() {
  const [be, setBe] = useState(null);
  const [tab, setTab] = useState("design");
  const [design, setDesign] = useState(() => ls("design", defaultDesign()));
  const [golden, setGolden] = useState(() => ls("golden", DEFAULT_GOLDEN));
  const [runs, setRuns] = useState(() => ls("runs", []));
  const [thr, setThr] = useState(() => ls("thr", DEFAULT_THRESHOLDS));
  const [data, setData] = useState(null), [dataErr, setDataErr] = useState(null), [proj, setProj] = useState(null);
  const [test, setTest] = useState(null);
  const [busy, setBusy] = useState(""), [jobMsg, setJobMsg] = useState(null), [running, setRunning] = useState(false);
  const appliedSig = useRef(null), [applied, setApplied] = useState(null);

  const connect = useCallback(async (prefer) => { setBe(null); setData(null); setProj(null); setTest(null); setBe(await openBackend(prefer)); }, []);
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
      const a = designToApi(d); await be.applyDesign(a); appliedSig.current = sig(d); setApplied(a.dataSource.vectorIngestionConfiguration.chunkingConfiguration);
      if (ingest) { const job = await be.ingest(); const s = job.statistics || {}; setJobMsg({ type: job.status === "COMPLETE" ? "success" : "error", text: `Ingestion job ${job.ingestionJobId}: ${job.status}. ${s.numberOfNewDocumentsIndexed ?? 0} documents indexed, ${s.numberOfDocumentsFailed ?? 0} failed${s.chunksAfter ? `, ${s.chunksAfter} chunks` : ""}.` }); await loadChunks(be); }
      else setJobMsg({ type: "success", text: "Design applied to the data source. Run ingestion to re-chunk and re-embed the documents." });
    } catch (e) { setJobMsg({ type: "error", text: `${e.code || "Error"}: ${e.message}` }); } finally { setBusy(""); }
  };

  const evaluate = async (which) => {
    setRunning(true);
    try {
      const d = which === "current" ? design : applyPreset(design, which), label = which === "current" ? design.name : PRESETS[which].label;
      if (sig(d) !== appliedSig.current) { await be.applyDesign(designToApi(d)); appliedSig.current = sig(d); await be.ingest(); await loadChunks(be); }   // re-chunk when the chunking config differs
      const o = retrievalOptions(d), k = d.rerank.enabled ? d.rerank.topN : d.retrieve.topK, t0 = performance.now(), rows = [];
      for (const g of golden.filter((x) => x.question)) {
        const [tr, rag] = await Promise.all([be.trace(g.question, o), be.rag(g.question, o)]);
        const retrieved = finalOf(tr), cites = (rag.citations || []).flatMap((c) => (c.retrievedReferences || []).map((r) => r.location?.s3Location?.uri));
        rows.push({ question: g.question, answer: rag.output?.text || "", scores: scoreRow(g, { retrieved, answer: rag.output?.text || "", citations: cites }, k) });
      }
      const run = { id: "run" + Date.now(), at: Date.now(), ms: performance.now() - t0, label, design: d, rows, aggregate: aggregate(rows.map((r) => r.scores)) };
      setRuns([run, ...runs]);
    } catch (e) { setJobMsg({ type: "error", text: `Evaluation failed: ${e.code || ""} ${e.message}` }); } finally { setRunning(false); }
  };

  if (!be) return <ContentLayout header={<Header variant="h1">RAG Studio</Header>}><Box>Connecting to knowledge base...</Box></ContentLayout>;
  return (
    <ContentLayout header={<Header variant="h1" description="Design, validate and test the retrieval-augmented generation pipeline of the knowledge layer, with before and after visualisations."
      actions={<SpaceBetween direction="horizontal" size="xs"><Button onClick={() => connect(be.mode === "fake" ? "auto" : "fake")}>{be.mode === "fake" ? "Try live knowledge base" : "Use demo corpus"}</Button></SpaceBetween>}>RAG Studio</Header>}>
      <SpaceBetween size="m">
        {be.reason && <Alert type="info" data-testid="studio-reason">{be.reason}</Alert>}
        {be.mode === "live-limited" && <Alert type="warning">The live backend has no inspect API yet: Design, Apply, Validate and Test work through the real wires; corpus and stage-score views are limited.</Alert>}
        <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
          { id: "design", label: "Design", content: <Design design={design} setDesign={setDesign} be={be} ctx={ctx} applied={applied} onApply={() => apply(design, false)} onIngest={() => apply(design, true)} busy={busy} jobMsg={jobMsg} kbKey={be.kb?.name || "demo"} /> },
          { id: "validate", label: "Validate", content: <Validate design={design} setDesign={setDesign} ctx={ctx} golden={golden} setGolden={setGolden} runs={runs} onRun={evaluate} running={running} thr={thr} setThr={setThr} /> },
          { id: "test", label: "Test", content: <Test be={be} design={design} opts={opts} test={test} setTest={setTest} goPost={() => setTab("post")} /> },
          { id: "corpus", label: "Corpus (pre-RAG)", content: <Corpus data={data} proj={proj} err={dataErr} /> },
          { id: "post", label: "Query analysis (post-RAG)", content: <PostRag test={test} data={data} proj={proj} runs={runs} thr={thr} /> },
        ]} />
      </SpaceBetween>
    </ContentLayout>
  );
}
