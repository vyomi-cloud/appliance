/* Real (small-head) training jobs: shared contract helpers for the three consoles (lane trainui). Pure functions, no React.
 * Contract: job record extension `vyomiTraining` = {engine, taskType, status, progress, epoch, epochs, metrics[], heldOut{accuracy,baseline},
 * rows, artifact, startedAt, endedAt, note}. The trained thing is a small classifier/reranker head on a frozen embedding model. */
export const CAPS = { rows: 2000, bytes: 5 * 1024 * 1024, labels: 20 };
export const TRAINABLE_BASES = [
  { id: "all-minilm-l6-v2", name: "all-MiniLM-L6-v2 (embedding model, Nano)" },
  { id: "nomic-embed-text", name: "nomic-embed-text (embedding model, offline / Mesh)" },
];
export const TASKS = [
  { id: "classifier", label: "Classifier", help: 'JSONL rows: {"text": "...", "label": "..."}' },
  { id: "router", label: "Router", help: 'JSONL rows: {"text": "...", "label": "<route name>"}' },
  { id: "reranker", label: "Reranker", help: 'JSONL rows: {"query": "...", "positive": "...", "negative": "..."}' },
];
export const HONEST = "Trained in this simulator on the embedding model: a small classifier/reranker head, not a language model. It cannot generate text.";
export const NON_TRAINABLE = "This base model is not trainable here. The job records metadata only and nothing is trained.";
export const KEEP_TAB_OPEN = "Keep this tab open while training: on Nano the training runs inside this browser tab and stops if you close it.";
export const ACTIVE = ["Queued", "Embedding", "Training", "Evaluating"];

export const bareId = (idOrArn) => String(idOrArn || "").replace(/^arn:.*\//, "").replace(/^.*\/models\//, "").replace(/^publishers\/[^/]+\/models\//, "");
export const isTrainableBase = (idOrArn) => { const s = bareId(idOrArn); return TRAINABLE_BASES.some((b) => b.id === s) || s.startsWith("vyomi.head."); };
export const isActive = (status) => ACTIVE.includes(status);
export const isNano = () => document.querySelector('meta[name="vyomi-substrate"]')?.content === "nano";
export const pct = (x) => (x == null || Number.isNaN(Number(x)) ? "-" : `${(Number(x) * 100).toFixed(1)}%`);
export const num = (x, d = 3) => (x == null || Number.isNaN(Number(x)) ? "-" : Number(x).toFixed(d));

/** The `vyomiTraining` block of any job record (null when the job is metadata-only). Tolerates missing fields. */
export function trainingOf(job) {
  const t = job?.vyomiTraining;
  if (!t) return null;
  return { engine: t.engine, taskType: t.taskType || "classifier", status: t.status || "Queued", progress: Math.max(0, Math.min(1, Number(t.progress) || 0)),
    epoch: t.epoch || 0, epochs: t.epochs || 0, metrics: t.metrics || [], heldOut: t.heldOut || null, rows: t.rows || 0, artifact: t.artifact || "",
    startedAt: t.startedAt, endedAt: t.endedAt, note: t.note || "" };
}

/** Client-side check of a training JSONL against the shared caps, so the user sees WHY before the cloud's own validation error. */
export function validateJsonl(text, taskType, sizeBytes) {
  const errors = [], bytes = sizeBytes ?? new Blob([text || ""]).size;
  if (bytes > CAPS.bytes) errors.push(`The file is ${(bytes / 1048576).toFixed(1)} MB; the limit is ${CAPS.bytes / 1048576} MB.`);
  if (text == null) return { ok: !errors.length, rows: 0, bytes, labels: [], errors, preview: [] };
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length > CAPS.rows) errors.push(`The file has ${lines.length} rows; the limit is ${CAPS.rows}.`);
  if (!lines.length) errors.push("The file has no rows.");
  const labels = new Set(), preview = [], need = taskType === "reranker" ? ["query", "positive", "negative"] : ["text", "label"];
  let bad = 0;
  lines.slice(0, CAPS.rows + 1).forEach((l, i) => {
    let o; try { o = JSON.parse(l); } catch { if (bad++ < 3) errors.push(`Row ${i + 1} is not valid JSON.`); return; }
    const miss = need.filter((k) => typeof o?.[k] !== "string" || !o[k].trim());
    if (miss.length) { if (bad++ < 3) errors.push(`Row ${i + 1} is missing ${miss.map((k) => `"${k}"`).join(", ")} (a ${taskType} needs ${need.join(", ")}).`); return; }
    if (taskType !== "reranker") labels.add(o.label);
    if (preview.length < 3) preview.push(o);
  });
  if (bad > 3) errors.push(`${bad - 3} more rows have problems.`);
  if (taskType !== "reranker") {
    if (labels.size > CAPS.labels) errors.push(`The file has ${labels.size} distinct labels; the limit is ${CAPS.labels}.`);
    if (labels.size === 1) errors.push("A classifier needs at least 2 distinct labels.");
  }
  return { ok: !errors.length, rows: lines.length, bytes, labels: [...labels], errors, preview };
}

/** Parse an object-store URI ("s3://b/k", "gs://b/k") into bucket + key. */
export const splitUri = (uri) => { const m = String(uri || "").match(/^(?:s3|gs):\/\/([^/]+)\/?(.*)$/); return m ? { bucket: m[1], key: m[2] } : null; };
