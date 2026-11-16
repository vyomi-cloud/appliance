/* In-process fake of the trainengine lane for the training UI: serves the SHARED CONTRACT (job record extension `vyomiTraining`) on the three
 * clouds' native shapes, so the consoles run without a backend. Time-driven job (about 7 s), deterministic metrics, keyword-based "model".
 * Usage (Playwright): await installTrainingFake(context)  (needs the context created with serviceWorkers: "block"). */
export const DURATION_MS = 7000, EPOCHS = 8, LABELS = ["maintenance", "safety", "billing"];
const row = (i) => { const l = LABELS[i % 3]; return JSON.stringify({ text: `${["ac unit leaking", "fire door propped open", "invoice shows wrong total"][i % 3]} ticket ${i}`, label: l }); };
const FILES = {
  "tickets.jsonl": Array.from({ length: 60 }, (_, i) => row(i)).join("\n"),
  "too-many.jsonl": Array.from({ length: 2500 }, (_, i) => row(i)).join("\n"),
  "one-label.jsonl": Array.from({ length: 30 }, () => row(0)).join("\n"),
  "bad-rows.jsonl": [row(0), JSON.stringify({ text: "no label here" }), "not json", row(1)].join("\n"),
  "pairs.jsonl": Array.from({ length: 40 }, (_, i) => JSON.stringify({ query: `q${i}`, positive: `relevant ${i}`, negative: `unrelated ${i}` })).join("\n"),
};
const SIZES = { "huge.jsonl": 6 * 1048576 };   // declared size only (never fetched)
const jobs = new Map();
let seq = 1;
const classify = (text) => { const t = String(text).toLowerCase(); const k = /fire|door|safety|smoke/.test(t) ? 1 : /invoice|bill|total|charge/.test(t) ? 2 : 0; const s = LABELS.map((_, i) => (i === k ? 0.82 : 0.09)); return { label: LABELS[k], scores: Object.fromEntries(LABELS.map((l, i) => [l, s[i]])) }; };
function vt(j) {
  if (j.stopped) j.frozen ??= Math.min(1, (Date.now() - j.t0) / DURATION_MS);
  const f = j.stopped ? j.frozen : Math.min(1, (Date.now() - j.t0) / DURATION_MS);
  const epoch = Math.floor(f * EPOCHS), done = f >= 1 && !j.stopped;
  const status = j.stopped ? "Stopped" : done ? "Completed" : f < 0.12 ? "Embedding" : f < 0.9 ? "Training" : "Evaluating";
  const metrics = Array.from({ length: done ? EPOCHS : epoch }, (_, i) => ({ epoch: i + 1, loss: +(1.1 * Math.exp(-0.45 * (i + 1)) + 0.05).toFixed(4), accuracy: +(1 - 0.55 * Math.exp(-0.5 * (i + 1))).toFixed(4) }));
  return { engine: "nano-head-js", taskType: j.task, status, progress: done ? 1 : +f.toFixed(3), epoch: done ? EPOCHS : epoch, epochs: EPOCHS, metrics, heldOut: done ? { accuracy: 0.9167, baseline: 0.3333 } : null, rows: j.rows,
    artifact: done ? `s3://train-data/models/${j.name}/head.json` : "", startedAt: new Date(j.t0).toISOString(), endedAt: done || j.stopped ? new Date(j.t0 + DURATION_MS).toISOString() : null, note: done ? "Embedded 60 rows with all-MiniLM-L6-v2, trained a softmax head, evaluated on 20% held out." : "" };
}
const rowsOf = (uri) => { const k = String(uri).split("/").pop(); return (FILES[k] || "").split("\n").filter(Boolean).length; };
const ok = (o, st = 200) => ({ status: st, type: "application/json", body: JSON.stringify(o) });
const xml = (b) => ({ status: 200, type: "application/xml", body: `<?xml version="1.0"?>${b}` });
const err = (st, code, message) => ({ status: st, type: "application/json", body: JSON.stringify({ message, __type: code, error: { code: st, status: code, message } }) });

function aws(m, p, q, body) {
  if (m === "GET" && p === "/") return xml(`<ListAllMyBucketsResult><Buckets><Bucket><Name>train-data</Name><CreationDate>2026-11-15T00:00:00Z</CreationDate></Bucket></Buckets></ListAllMyBucketsResult>`);
  const s3 = p.match(/^\/train-data(?:\/(.*))?$/);
  if (s3 && m === "GET" && !s3[1]) return xml(`<ListBucketResult><IsTruncated>false</IsTruncated>${[...Object.keys(FILES), ...Object.keys(SIZES)].map((k) => `<Contents><Key>${k}</Key><Size>${SIZES[k] ?? FILES[k].length}</Size><LastModified>2026-11-15T00:00:00Z</LastModified></Contents>`).join("")}</ListBucketResult>`);
  if (s3 && m === "GET") return { status: 200, type: "application/x-ndjson", body: FILES[decodeURIComponent(s3[1])] ?? "" };
  if (p === "/foundation-models") return ok({ modelSummaries: [{ modelId: "amazon.nova-lite-v1:0", modelName: "Nova Lite", providerName: "Amazon", outputModalities: ["TEXT"] }] });
  if (p === "/custom-models") return ok({ modelSummaries: [...jobs.values()].filter((j) => j.cloud === "aws" && vt(j).status === "Completed").map((j) => ({ modelArn: j.modelArn, modelName: j.cname, baseModelName: j.base, modelStatus: "Active", customizationType: "FINE_TUNING", creationTime: new Date(j.t0).toISOString() })) });
  const rec = (j) => { const t = vt(j); return { jobArn: j.arn, jobName: j.name, customModelName: j.cname, baseModelArn: `arn:aws:bedrock:us-east-1::foundation-model/${j.base}`, customizationType: "FINE_TUNING", status: t.status === "Completed" ? "Completed" : t.status === "Stopped" ? "Stopped" : "InProgress", creationTime: new Date(j.t0).toISOString(), outputModelArn: t.status === "Completed" ? j.modelArn : undefined, outputModelName: j.cname, vyomiTraining: j.trainable ? t : undefined }; };
  if (m === "GET" && p === "/model-customization-jobs") return ok({ modelCustomizationJobSummaries: [...jobs.values()].filter((j) => j.cloud === "aws").map(rec) });
  if (m === "POST" && p === "/model-customization-jobs") {
    const trainable = /^(all-minilm-l6-v2|nomic-embed-text)$/.test(body.baseModelIdentifier), id = `job${seq++}`;
    const rows = rowsOf(body.trainingDataConfig.s3Uri);
    if (trainable && rows > 2000) return err(400, "ValidationException", "Training data has more than 2000 rows.");
    const j = { cloud: "aws", id, name: body.jobName, cname: body.customModelName, base: body.baseModelIdentifier, trainable, task: body.hyperParameters.taskType || "classifier", rows, t0: Date.now(), arn: `arn:aws:bedrock:us-east-1:123456789012:model-customization-job/${id}`, modelArn: `arn:aws:bedrock:us-east-1:123456789012:custom-model/${body.customModelName}` };
    jobs.set(id, j); return ok({ jobArn: j.arn });
  }
  let r;
  if (m === "GET" && (r = p.match(/^\/model-customization-jobs\/(.+)$/))) { const j = jobs.get(decodeURIComponent(r[1]).split("/").pop()); return j ? ok(rec(j)) : err(404, "ResourceNotFoundException", "Job not found"); }
  if (m === "POST" && (r = p.match(/^\/model-customization-jobs\/(.+)\/stop$/))) { const j = jobs.get(decodeURIComponent(r[1]).split("/").pop()); if (j) j.stopped = true; return ok({}); }
  if (m === "POST" && /^\/model\/.+\/invoke$/.test(p)) return body.task === "classify" ? ok({ ...classify(body.text), vyomiTrained: true }) : ok({ score: 0.7312, vyomiTrained: true });
  return ok({});
}
function gcp(m, p, q, body) {
  if (m === "GET" && p === "/storage/v1/b") return ok({ items: [{ name: "train-data" }] });
  let r;
  if (m === "GET" && (r = p.match(/^\/storage\/v1\/b\/train-data\/o(?:\/(.+))?$/))) {
    if (!r[1]) return ok({ items: [...Object.keys(FILES), ...Object.keys(SIZES)].map((k) => ({ name: k, size: String(SIZES[k] ?? FILES[k].length) })) });
    const k = decodeURIComponent(r[1]);
    return q.alt === "media" ? { status: 200, type: "application/x-ndjson", body: FILES[k] ?? "" } : ok({ name: k, size: String(SIZES[k] ?? (FILES[k] || "").length) });
  }
  const rec = (j) => { const t = vt(j); return { name: j.arn, tunedModelDisplayName: j.name, baseModel: j.base, createTime: new Date(j.t0).toISOString(), state: t.status === "Completed" ? "JOB_STATE_SUCCEEDED" : t.status === "Stopped" ? "JOB_STATE_CANCELLED" : "JOB_STATE_RUNNING", supervisedTuningSpec: { trainingDatasetUri: j.uri },
    tunedModel: t.status === "Completed" ? { model: `projects/p/locations/us-central1/models/m${j.id}`, endpoint: `projects/p/locations/us-central1/endpoints/e${j.id}` } : undefined, vyomiTraining: j.trainable ? t : undefined }; };
  if (/\/tuningJobs$/.test(p) && m === "GET") return ok({ tuningJobs: [...jobs.values()].filter((j) => j.cloud === "gcp").map(rec) });
  if (/\/tuningJobs$/.test(p) && m === "POST") {
    const id = `${seq++}`, uri = body.supervisedTuningSpec.trainingDatasetUri, trainable = /^(all-minilm-l6-v2|nomic-embed-text)$/.test(body.baseModel);
    const j = { cloud: "gcp", id, name: body.tunedModelDisplayName, base: body.baseModel, trainable, task: body.supervisedTuningSpec.hyperParameters?.taskType || "classifier", uri, rows: rowsOf(uri), t0: Date.now(), arn: `projects/p/locations/us-central1/tuningJobs/${id}` };
    jobs.set(id, j); return ok(rec(j));
  }
  if ((r = p.match(/\/tuningJobs\/([^/:]+)(:cancel)?$/))) { const j = jobs.get(r[1]); if (!j) return err(404, "NOT_FOUND", "not found"); if (r[2]) { j.stopped = true; return ok({}); } return ok(rec(j)); }
  if (m === "POST" && /:predict$/.test(p)) { const i = body.instances[0]; return ok({ predictions: [i.query ? { score: 0.7312 } : classify(i.text)], vyomiTrained: true }); }
  return ok({});
}
function azure(m, p, q, body, raw) {
  if (m === "GET" && p === "/openai/files") return ok({ data: [{ id: "file-tickets", filename: "tickets.jsonl", bytes: FILES["tickets.jsonl"].length, purpose: "fine-tune" }, { id: "file-big", filename: "too-many.jsonl", bytes: 999, purpose: "fine-tune" }] });
  let r;
  if (m === "GET" && (r = p.match(/^\/openai\/files\/(.+)\/content$/))) return { status: 200, type: "application/x-ndjson", body: r[1] === "file-big" ? FILES["too-many.jsonl"] : FILES["tickets.jsonl"] };
  if (m === "POST" && p === "/openai/files") return ok({ id: "file-uploaded", filename: "up.jsonl", purpose: "fine-tune" });
  const rec = (j) => { const t = vt(j); return { id: j.id, object: "fine_tuning.job", model: j.base, training_file: j.file, created_at: Math.floor(j.t0 / 1000), status: t.status === "Completed" ? "succeeded" : t.status === "Stopped" ? "cancelled" : "running", fine_tuned_model: t.status === "Completed" ? `${j.base}.ft-${j.id}` : null, finished_at: t.status === "Completed" ? Math.floor((j.t0 + DURATION_MS) / 1000) : null, vyomiTraining: j.trainable ? t : undefined }; };
  if (m === "GET" && p === "/openai/fine_tuning/jobs") return ok({ data: [...jobs.values()].filter((j) => j.cloud === "azure").map(rec) });
  if (m === "POST" && p === "/openai/fine_tuning/jobs") { const id = `ftjob-${seq++}`, trainable = /^(all-minilm-l6-v2|nomic-embed-text)$/.test(body.model); const j = { cloud: "azure", id, name: id, base: body.model, trainable, task: body.hyperparameters?.taskType || "classifier", file: body.training_file, rows: 60, t0: Date.now() }; jobs.set(id, j); return ok(rec(j)); }
  if ((r = p.match(/^\/openai\/fine_tuning\/jobs\/([^/]+?)(\/cancel)?$/))) { const j = jobs.get(r[1]); if (!j) return err(404, "NotFound", "not found"); if (r[2]) { j.stopped = true; return ok(rec(j)); } return ok(rec(j)); }
  if (m === "POST" && /^\/openai\/deployments\/.+\/chat\/completions$/.test(p)) { const c = body.messages.at(-1).content; const o = c.startsWith("{") ? { content: "0.7312" } : classify(c); return ok({ choices: [{ message: { role: "assistant", content: o.label ?? o.content } }], vyomi: { scores: o.scores }, vyomiTrained: true }); }
  if (/providers\/Microsoft.CognitiveServices\/accounts/.test(p) || /providers\/Microsoft.Search/.test(p)) return ok({ value: [] });
  return ok({});
}

export async function installTrainingFake(context, log = []) {
  await context.addInitScript(() => { window.__vyomiNanoReady = true; });
  await context.route(/\/_wire\//, async (route) => {
    const req = route.request(), u = new URL(req.url()), p = u.pathname.replace(/^.*\/_wire/, ""), q = Object.fromEntries(u.searchParams);
    let body = {}; const pd = req.postData(); if (pd && /json/.test(req.headers()["content-type"] || "")) { try { body = JSON.parse(pd); } catch { /* not json */ } }
    const auth = req.headers().authorization || "";
    const res = p.startsWith("/openai") || p.startsWith("/subscriptions") ? azure(req.method(), p, q, body) : p.startsWith("/v1/") || p.startsWith("/storage/") ? gcp(req.method(), p, q, body)
      : /\/s3\//.test(auth) || /^\/(train-data|$)/.test(p) || /\/bedrock\//.test(auth) || p.startsWith("/model") || p === "/foundation-models" || p === "/custom-models" ? aws(req.method(), p, q, body) : ok({});
    log.push(`${req.method()} ${p}`);
    await route.fulfill({ status: res.status, contentType: res.type, body: res.body, headers: { "access-control-allow-origin": "*" } });
  });
  return { jobs };
}
