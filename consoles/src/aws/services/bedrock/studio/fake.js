/* In-process fake of the knowledge lane for RAG Studio: serves the SAME shapes as (a) bedrock-agent / bedrock-agent-runtime
 * (Retrieve, RetrieveAndGenerate, ingestion jobs, UpdateDataSource) and (b) the Vyomi inspect extension
 * (GET /_vyomi/kb/{id}/chunks, POST /_vyomi/kb/{id}/retrieve-trace). Used when no live facilities-kb inspect API answers
 * ("Demo corpus"), and by the node tests. The retrieval math is real (BM25 + hashed-n-gram vectors + weighted RRF + term-coverage rerank);
 * only the corpus is canned. The answer generator is extractive (no LLM), so faithfulness is real but fluency is not. */
import * as E from "./engine.js";

const D = (name, meta, text) => ({ uri: `s3://facilities-docs/${name}.txt`, metadata: meta, text });
export const CORPUS = [
  D("hvac-maintenance-policy-v2", { department: "hvac", site: "hq", doc_type: "policy", year: "2025" }, `HVAC maintenance policy. All HVAC air handling units must have their filters replaced every 90 days. Units serving laboratories or server rooms must have filters replaced every 60 days. Technicians record each replacement in the maintenance system with the unit identifier and the filter grade. Coils are cleaned twice a year, in spring and autumn. Refrigerant leak checks are performed quarterly by a certified technician. Any unit that fails a leak check must be isolated and a work order raised at priority one. Thermostat set points in occupied areas are 21 to 24 degrees Celsius and may not be changed by tenants. Out of hours HVAC requests are charged to the requesting department at the standard hourly rate.`),
  D("hvac-maintenance-policy-v1", { department: "hvac", site: "hq", doc_type: "policy", year: "2023" }, `HVAC maintenance policy. All HVAC air handling units must have their filters replaced every 90 days. Units serving laboratories or server rooms must have filters replaced every 60 days. Technicians record each replacement in the maintenance system with the unit identifier and the filter grade. Coils are cleaned once a year in spring. Refrigerant leak checks are performed annually by a certified technician. Thermostat set points in occupied areas are 21 to 24 degrees Celsius.`),
  D("work-order-approval-policy", { department: "operations", site: "all", doc_type: "policy", year: "2025" }, `Work order approval policy. Every maintenance work order is created in the facilities system with a priority from one to four. Work orders above 5000 dollars need manager approval before any vendor is dispatched. Work orders above 25000 dollars additionally need finance director approval. Emergency work orders at priority one may start immediately but must be approved retroactively within 24 hours. Approvers receive a notification in the approver inbox and may approve, reject or ask for changes. Every decision is written to the approval ledger with the approver identity and timestamp. Rejected work orders are closed and the requester is notified with the reason.`),
  D("fire-safety-handbook", { department: "safety", site: "all", doc_type: "handbook", year: "2024" }, `Fire safety handbook. Fire extinguishers are inspected monthly by the floor warden and tagged with the inspection date. A full service by an external contractor is carried out every year. Fire alarm panels are tested weekly and the test result is logged. Evacuation drills take place twice a year in every building and the assembly point must be reached within five minutes. Fire doors must never be propped open. Blocked exits must be reported to the safety office immediately. New employees receive fire safety training in their first week.`),
  D("elevator-service-log", { department: "elevators", site: "hq", doc_type: "log", year: "2025" }, `Elevator service log. March 4: Elevator 3 door sensor fault, door reopened repeatedly, sensor replaced by vendor. March 11: Elevator 1 routine inspection passed. March 19: Elevator 2 slow leveling at floor 7, adjusted. April 2: Elevator 3 door sensor fault recurred, vendor escalated, root cause traced to wiring harness. April 9: Elevator 3 harness replaced, monitored for a week, no repeat. April 22: All elevators annual safety certificate renewed.`),
  D("parking-policy", { department: "admin", site: "hq", doc_type: "policy", year: "2024" }, `Parking policy. Twenty visitor parking spaces are reserved at the headquarters and are free for up to four hours. Employee permits are issued by the admin office and must be displayed on the dashboard. Electric vehicle charging bays are limited to a four hour session. Accessible spaces are never assigned to permit holders. Motorcycles park in the marked area near gate two. Unauthorised vehicles may be towed after a written warning. Contractors receive temporary permits valid for the length of the work order.`),
  D("vendor-contract-chillers", { department: "hvac", site: "hq", doc_type: "contract", year: "2025" }, `Chiller maintenance contract. The vendor provides a four hour response for critical chiller failures and next business day response for non critical faults. Planned maintenance visits take place quarterly. Spare parts held on site are replenished within ten days. The vendor must provide a written root cause report within five working days of any critical failure. Service credits of two percent of the monthly fee apply for each missed response window. The contract runs for three years with an option to renew. Contact the vendor desk at support@chillerworks.example or +1 555 010 7788.`),
  D("cleaning-schedule", { department: "admin", site: "hq", doc_type: "schedule", year: "2025" }, `Cleaning schedule. Common areas are cleaned every weekday morning before eight. Restrooms are cleaned three times a day and checked hourly in the afternoon. Meeting rooms are cleaned after bookings that include food. Carpets are deep cleaned every quarter and windows twice a year. Spills must be reported to the helpdesk which raises a priority three work order. Waste is separated into recycling, compost and general bins in every kitchen area.`),
  D("energy-usage-report-q1", { department: "operations", site: "hq", doc_type: "report", year: "2025" }, `Energy usage report for the first quarter. Total electricity consumption was 412 megawatt hours, down six percent on the previous quarter. HVAC accounts for 48 percent of consumption, lighting for 21 percent and data rooms for 18 percent. The chiller plant ran at an average efficiency of 0.62 kilowatts per ton. Replacing the remaining fluorescent fixtures with LED is projected to save 35 megawatt hours per year. Peak demand occurred on the second Tuesday of February during a cold snap.`),
  D("security-access-procedure", { department: "security", site: "all", doc_type: "procedure", year: "2024" }, `Security access procedure. Badges are issued by the security office after identity verification and expire after twelve months. Lost badges must be reported within one hour so that they can be deactivated. Visitors sign in at reception, receive a printed pass and must be escorted at all times in restricted areas. Server rooms require a second approver for any contractor entry. Access logs are retained for one year and reviewed monthly. Tailgating through a controlled door is a policy violation.`),
  D("plomberie-procedure-fr", { department: "plumbing", site: "paris", doc_type: "procedure", year: "2024" }, `Procédure de plomberie. Les fuites d'eau doivent être signalées à la maintenance dans les plus brefs délais. Le technicien ferme la vanne principale et pose une pancarte sur la zone. Une intervention est ouverte pour une réparation dans les vingt quatre heures. Les chauffe-eau sont vérifiés une fois par an avec le détartrage.`),
  D("emergency-contacts-sheet", { department: "safety", site: "all", doc_type: "handbook", year: "2025" }, `Emergency contacts. Facilities duty manager: Priya Raman, priya.raman@facilities.example, +1 555 010 4412. Security control room: extension 1000. Fire brigade: 911. In an evacuation the floor warden carries the roll call sheet and reports to the incident controller at the assembly point. The duty manager SSN-style staff id 123-45-6789 must not be shared externally.`),
];

const LAT = () => performance.now();
export function createFake(corpus = CORPUS) {
  const kb = { knowledgeBaseId: "KBFAKE0001", name: "facilities-kb", status: "ACTIVE", updatedAt: new Date().toISOString() };
  const ds = { dataSourceId: "DSFAKE0001", name: "facilities-docs", status: "AVAILABLE" };
  let chunking = { chunkingStrategy: "FIXED_SIZE", fixedSizeChunkingConfiguration: { maxTokens: 48, overlapPercentage: 20 } };
  let chunks = [], bm = null, jobs = [];
  const design = () => E.apiToDesign(chunking).chunk;
  function build() {
    const cfg = design(); chunks = [];
    corpus.forEach((doc, di) => E.chunkText(doc.text, cfg).forEach((c, ci) => chunks.push({ id: `c${di}-${ci}`, uri: doc.uri, text: c.text, tokens: E.countTokens(c.text), metadata: { ...doc.metadata, chunk_index: ci }, pii: E.piiScan(c.text), lang: E.detectLang(c.text), embedding: E.hashEmbed(c.text) })));
    bm = E.bm25Index(chunks);
  }
  build();
  const tick = (ms = 4) => new Promise((r) => setTimeout(r, ms));
  const api = {
    mode: "fake", label: "Demo corpus (in-browser fake)",
    async listKbs() { return [kb]; },
    async getKb() { return kb; },
    async getDataSource() { return { ...ds, vectorIngestionConfiguration: { chunkingConfiguration: chunking } }; },
    async applyDesign(a) { chunking = a.dataSource.vectorIngestionConfiguration.chunkingConfiguration; kb.updatedAt = new Date().toISOString(); return { dataSourceId: ds.dataSourceId, chunkingConfiguration: chunking }; },
    async ingest() { await tick(30); const prev = chunks.length; build(); const job = { ingestionJobId: "JOB" + (jobs.length + 1), status: "COMPLETE", startedAt: new Date().toISOString(), statistics: { numberOfDocumentsScanned: corpus.length, numberOfNewDocumentsIndexed: corpus.length, numberOfModifiedDocumentsIndexed: 0, numberOfDocumentsDeleted: 0, numberOfDocumentsFailed: 0, chunksBefore: prev, chunksAfter: chunks.length } }; jobs.unshift(job); return job; },
    async jobs() { return jobs; },
    async chunks() { return { knowledgeBaseId: kb.knowledgeBaseId, embeddingModel: "hash-ngram-256", chunks: chunks.map((c) => ({ ...c })) }; },
    async trace(query, o) {
      const t0 = LAT(), lat = {}, mark = (k, t) => { lat[k] = +(LAT() - t).toFixed(2); };
      let t = LAT(); const qv = E.hashEmbed(query); mark("embed", t);
      const filtered = [], pass = [];
      for (const c of chunks) { if (o.filter && String(c.metadata[o.filter.key]) !== String(o.filter.value)) filtered.push(c); else pass.push(c); }
      t = LAT(); const vs = pass.map((c) => ({ c, s: E.cosine(qv, c.embedding) })).sort((a, b) => b.s - a.s); mark("vector", t);
      t = LAT(); const bs = pass.map((c) => ({ c, s: bm.score(query, c.id) })).sort((a, b) => b.s - a.s); mark("bm25", t);
      const vr = new Map(vs.map((x, i) => [x.c.id, i + 1])), br = new Map(bs.map((x, i) => [x.c.id, i + 1])), vsc = new Map(vs.map((x) => [x.c.id, x.s])), bsc = new Map(bs.map((x) => [x.c.id, x.s]));
      t = LAT(); const w = o.searchType === "SEMANTIC" ? 1 : o.hybridWeight;
      let pool = pass.map((c) => ({ c, f: o.searchType === "SEMANTIC" ? 1 / (60 + vr.get(c.id)) : E.fuse(vr.get(c.id), br.get(c.id), w) }));
      if (o.searchType !== "SEMANTIC") pool = pool.filter((x) => vsc.get(x.c.id) > 0.02 || bsc.get(x.c.id) > 0);
      pool.sort((a, b) => b.f - a.f); pool = pool.slice(0, o.numberOfResults); mark("fuse", t);
      t = LAT(); const rr = new Map(pool.map((x) => [x.c.id, E.rerankScore(query, x.c)]));
      let finalIds;
      if (o.rerank) finalIds = [...pool].sort((a, b) => rr.get(b.c.id) - rr.get(a.c.id)).slice(0, o.rerankTopN).map((x) => x.c.id); else finalIds = pool.slice(0, Math.min(o.numberOfResults, o.rerankTopN || o.numberOfResults)).map((x) => x.c.id);
      mark("rerank", t); lat.total = +(LAT() - t0).toFixed(2);
      const results = pool.map((x, i) => ({ id: x.c.id, uri: x.c.uri, text: x.c.text, tokens: x.c.tokens, metadata: x.c.metadata, vector_score: +vsc.get(x.c.id).toFixed(4), vector_rank: vr.get(x.c.id), bm25_score: +bsc.get(x.c.id).toFixed(4), bm25_rank: br.get(x.c.id), fused_rank: i + 1, rerank_score: o.rerank ? +rr.get(x.c.id).toFixed(4) : null, filtered_out_reason: null, final_rank: finalIds.indexOf(x.c.id) + 1 || null }));
      const fe = filtered.map((c) => ({ c, s: E.cosine(qv, c.embedding) })).sort((a, b) => b.s - a.s).slice(0, 3).filter((x) => x.s > 0.05);
      for (const x of fe) results.push({ id: x.c.id, uri: x.c.uri, text: x.c.text, tokens: x.c.tokens, metadata: x.c.metadata, vector_score: +x.s.toFixed(4), vector_rank: null, bm25_score: null, bm25_rank: null, fused_rank: null, rerank_score: null, filtered_out_reason: `metadata filter ${o.filter.key} = "${o.filter.value}" excludes ${x.c.metadata[o.filter.key]}`, final_rank: null });
      const top = results.find((r) => r.final_rank === 1);
      return { query, options: o, queryEmbedding: qv, results, latencyMs: lat, confidence: top ? E.rerankScore(query, top) : 0, embeddingModel: "hash-ngram-256" };
    },
    async retrieve(query, o) { const tr = await api.trace(query, o); return { retrievalResults: tr.results.filter((r) => r.final_rank).sort((a, b) => a.final_rank - b.final_rank).map((r) => ({ content: { type: "TEXT", text: r.text }, location: { type: "S3", s3Location: { uri: r.uri } }, metadata: r.metadata, score: r.rerank_score ?? r.vector_score })) }; },
    async rag(query, o) {
      const guard = E.piiScan(query).length || /\b(password|salary|home address)\b/i.test(query);
      if (guard) return { output: { text: "Sorry, the model cannot answer this question." }, citations: [], guardrailAction: "INTERVENED", guardrail: { input: E.piiScan(query).length ? "sensitive-information: PII in the question" : "denied topic" }, sessionId: "fake" };
      const tr = await api.trace(query, o), fin = tr.results.filter((r) => r.final_rank).sort((a, b) => a.final_rank - b.final_rank);
      if (!fin.length || tr.confidence < o.threshold) return { output: { text: "I cannot answer that from the knowledge base: no sufficiently relevant source was found." }, citations: [], guardrailAction: "NONE", grounded: false, sessionId: "fake" };
      const q = E.contentTokens(query).map((x) => x.replace(/(ing|ed|es|s)$/, "")), picks = [];
      for (const r of fin.slice(0, 3)) for (const s of E.splitSentences(r.text)) { const st = new Set(E.contentTokens(s).map((x) => x.replace(/(ing|ed|es|s)$/, ""))), cov = q.filter((x) => st.has(x)).length / Math.max(1, q.length); if (cov > 0.3 && !picks.some((p) => p.s === s)) picks.push({ s, cov, r }); }
      picks.sort((a, b) => b.cov - a.cov); const use = picks.slice(0, 2);
      if (!use.length) return { output: { text: "I cannot answer that from the knowledge base: no sufficiently relevant source was found." }, citations: [], guardrailAction: "NONE", grounded: false, sessionId: "fake" };
      let text = "", cit = [];
      for (const p of use) { const start = text.length; text += (text ? " " : "") + p.s; cit.push({ generatedResponsePart: { textResponsePart: { text: p.s, span: { start, end: text.length } } }, retrievedReferences: [{ content: { text: p.r.text }, location: { type: "S3", s3Location: { uri: p.r.uri } }, metadata: p.r.metadata }] }); }
      return { output: { text }, citations: o.citations === false ? [] : cit, guardrailAction: "NONE", grounded: true, sessionId: "fake" };
    },
  };
  return api;
}
