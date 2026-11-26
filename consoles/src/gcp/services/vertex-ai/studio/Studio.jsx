/* GCP RAG Studio (Vertex AI > RAG Studio): design, validate, test and visualise (pre/post) the RAG Engine corpus.
 * Live against the simulator's Vertex AI RAG Engine (+ the Vyomi inspect API) or an in-browser demo corpus; exports/imports vyomi.rag-design/v1. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Box, Button, Stack, Tab, Tabs, Typography } from "@mui/material";
import { PageHeader } from "../../../kit/common.jsx";
import Crumbs from "../Crumbs.jsx";
import { DEFAULT_GOLDEN, DEFAULT_THRESHOLDS, PRESETS, aggregate, applyPreset, corpusStats, retrievalOptions, scoreRow } from "../../../../common/ragstudio/engine.js";
import { projectChunks } from "../../../../common/ragstudio/project.js";
import { openBackend, seedDemoCorpus } from "./backend.js";
import { designToApi, gcpDefaultDesign } from "./gcpMap.js";
import Design from "./Design.jsx";
import Validate from "./Validate.jsx";
import Test, { citedUris, finalOf } from "./Test.jsx";
import Corpus from "./Corpus.jsx";
import PostRag from "./PostRag.jsx";

const ls = (k, d) => { try { const v = localStorage.getItem("vyomi.ragstudio.gcp." + k); return v ? JSON.parse(v) : d; } catch { return d; } };
const lset = (k, v) => { try { localStorage.setItem("vyomi.ragstudio.gcp." + k, JSON.stringify(v)); } catch { /* private mode */ } };
const sig = (d) => JSON.stringify(designToApi(d).transformation);
const TABS = [["design", "Design"], ["validate", "Validate"], ["test", "Test"], ["corpus", "Corpus (pre-RAG)"], ["post", "Query analysis (post-RAG)"]];

export default function RagStudio() {
  const [be, setBe] = useState(null), [tab, setTab] = useState("design");
  const [design, setDesign] = useState(() => ls("design", gcpDefaultDesign()));
  const [golden, setGolden] = useState(() => ls("golden", DEFAULT_GOLDEN)), [runs, setRuns] = useState(() => ls("runs", [])), [thr, setThr] = useState(() => ls("thr", DEFAULT_THRESHOLDS));
  const [data, setData] = useState(null), [dataErr, setDataErr] = useState(null), [proj, setProj] = useState(null), [test, setTest] = useState(null);
  const [busy, setBusy] = useState(""), [jobMsg, setJobMsg] = useState(null), [running, setRunning] = useState(false), [applied, setApplied] = useState(null);
  const appliedSig = useRef(null);

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
      const a = designToApi(d); await be.applyDesign(a); appliedSig.current = sig(d); setApplied(a.transformation.ragFileChunkingConfig.fixedLengthChunking);
      if (ingest) { const job = await be.ingest(), s = job.statistics || {}; setJobMsg({ type: job.status === "COMPLETE" ? "success" : "error", text: `Ingestion ${job.ingestionJobId}: ${job.status}. ${s.numberOfNewDocumentsIndexed ?? 0} files indexed, ${s.numberOfDocumentsFailed ?? 0} failed${s.chunksAfter ? `, ${s.chunksAfter} chunks` : ""}.` }); await loadChunks(be); }
      else setJobMsg({ type: "success", text: "Design applied. Run ingestion (Apply and ingest) to re-chunk and re-embed the corpus files." });
    } catch (e) { setJobMsg({ type: "error", text: `${e.code || "Error"}: ${e.message}` }); } finally { setBusy(""); }
  };
  const seed = async () => {
    setBusy("ingest"); setJobMsg(null);
    try { await seedDemoCorpus(design); setJobMsg({ type: "success", text: "Created facilities-corpus in the simulator and uploaded the demo documents." }); await connect("auto"); } catch (e) { setJobMsg({ type: "error", text: `${e.code || "Error"}: ${e.message}` }); } finally { setBusy(""); }
  };

  const evaluate = async (which) => {
    setRunning(true);
    try {
      const d = which === "current" ? design : applyPreset(design, which), label = which === "current" ? design.name : PRESETS[which].label;
      if (sig(d) !== appliedSig.current) { await be.applyDesign(designToApi(d)); appliedSig.current = sig(d); await be.ingest(); await loadChunks(be); }   // re-chunk when the chunking config differs
      const o = retrievalOptions(d), k = d.rerank.enabled ? d.rerank.topN : d.retrieve.topK, t0 = performance.now(), rows = [];
      for (const g of golden.filter((x) => x.question)) {
        const [tr, rag] = await Promise.all([be.trace(g.question, o), be.rag(g.question, { ...o, model: d.generate.model, citations: d.generate.citations }).catch(() => ({ output: { text: "" }, citations: [] }))]);
        rows.push({ question: g.question, answer: rag.output?.text || "", scores: scoreRow(g, { retrieved: finalOf(tr), answer: rag.output?.text || "", citations: citedUris(rag) }, k) });
      }
      setRuns([{ id: "run" + Date.now(), at: Date.now(), ms: performance.now() - t0, label, design: d, rows, aggregate: aggregate(rows.map((r) => r.scores)) }, ...runs]);
    } catch (e) { setJobMsg({ type: "error", text: `Evaluation failed: ${e.code || ""} ${e.message}` }); } finally { setRunning(false); }
  };

  const head = (
    <>
      <Crumbs trail={[{ text: "Agent Platform", href: "#/vertex-ai" }, { text: "Agents", href: "#/vertex-ai/agent-garden" }, { text: "RAG Studio" }]} />
      <PageHeader title="RAG Studio" actions={be && <Button variant="outlined" onClick={() => connect(be.mode === "fake" ? "auto" : "fake")} data-testid="toggle-backend">{be.mode === "fake" ? "Try live RAG Engine" : "Use demo corpus"}</Button>} />
    </>
  );
  if (!be) return <Box>{head}<Typography>Connecting to the RAG Engine...</Typography></Box>;
  return (
    <Box>
      {head}
      <Stack spacing={2}>
        <Typography variant="body2" color="text.secondary">Design, validate and test the retrieval-augmented generation pipeline of a Vertex AI RAG Engine corpus, with before and after visualisations. Designs export as the cloud-neutral vyomi.rag-design/v1 document.</Typography>
        {be.reason && <Alert severity="info" data-testid="studio-reason">{be.reason}</Alert>}
        {be.mode === "live-limited" && <Alert severity="warning">The backend has no inspect API yet: Design, Apply, Validate and Test work through the real wires; corpus and stage-score views are limited.</Alert>}
        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto" data-testid="studio-tabs">{TABS.map(([id, l]) => <Tab key={id} value={id} label={l} data-testid={`tab-${id}`} />)}</Tabs>
        {tab === "design" && <Design design={design} setDesign={setDesign} golden={golden} setGolden={setGolden} be={be} ctx={ctx} applied={applied} onApply={() => apply(design, false)} onIngest={() => apply(design, true)} busy={busy} jobMsg={jobMsg} onSeed={seed} />}
        {tab === "validate" && <Validate design={design} setDesign={setDesign} ctx={ctx} golden={golden} setGolden={setGolden} runs={runs} onRun={evaluate} running={running} thr={thr} setThr={setThr} />}
        {tab === "test" && <Test be={be} design={design} opts={opts} test={test} setTest={setTest} goPost={() => setTab("post")} />}
        {tab === "corpus" && <Corpus data={data} proj={proj} err={dataErr} />}
        {tab === "post" && <PostRag test={test} data={data} proj={proj} runs={runs} thr={thr} />}
      </Stack>
    </Box>
  );
}
