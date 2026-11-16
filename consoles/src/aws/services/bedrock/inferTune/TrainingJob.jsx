/* Custom-model customization job detail for a REAL head-training job: status, progress, per-epoch loss/accuracy, held-out accuracy vs
 * baseline, stop, artifact, and a "Try it" panel that calls InvokeModel on the trained custom model. Metadata-only jobs show their note. */
import { useEffect, useRef, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import { ErrorAlert } from "../../../kit/common.jsx";
import { HeldOutBars, ScoreBars, TrainingChart, TrainingProgress } from "../../../../common/TrainingViz.jsx";
import { HONEST, KEEP_TAB_OPEN, NON_TRAINABLE, TASKS, isActive, isNano, pct, trainingOf } from "../../../../common/training.js";
import * as api from "./api.js";
import { Page, jobStatus, modelOf, when } from "./Shared.jsx";

const Kv = ({ label, children, id }) => <div><Box variant="awsui-key-label">{label}</Box><div data-testid={id}>{children ?? "-"}</div></div>;

function TryIt({ job, t }) {
  const [mode, setMode] = useState(t.taskType === "reranker" ? "score" : "classify");
  const [text, setText] = useState(""), [doc, setDoc] = useState(""), [out, setOut] = useState(null), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const target = job.outputModelArn || job.outputModelName || job.customModelName;
  const run = async () => {
    setBusy(true); setErr(null); setOut(null);
    try { setOut(await api.invokeCustomModel(target, mode === "classify" ? { task: "classify", text } : { task: "score", query: text, document: doc })); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <SpaceBetween size="m">
      <Tabs activeTabId={mode} onChange={({ detail }) => { setMode(detail.activeTabId); setOut(null); }} tabs={[
        { id: "classify", label: "Classify text", disabled: t.taskType === "reranker" }, { id: "score", label: "Score query and document", disabled: t.taskType !== "reranker" }]} />
      <Textarea value={text} onChange={({ detail }) => setText(detail.value)} placeholder={mode === "classify" ? "Text to classify" : "Query"} ariaLabel={mode === "classify" ? "Text to classify" : "Query"} rows={3} />
      {mode === "score" && <Textarea value={doc} onChange={({ detail }) => setDoc(detail.value)} placeholder="Document" ariaLabel="Document" rows={3} />}
      <div><Button variant="primary" loading={busy} disabled={!text || (mode === "score" && !doc)} onClick={run}>Run</Button></div>
      {err && <ErrorAlert error={err} header="InvokeModel failed" />}
      {out && (
        <Container header={<Header variant="h3">Result</Header>}>
          <SpaceBetween size="s">
            {out.label != null && <div data-testid="try-label"><Box variant="awsui-key-label">Predicted label</Box><Box variant="h2">{out.label}</Box></div>}
            {out.score != null && <div data-testid="try-score"><Box variant="awsui-key-label">Relevance score</Box><Box variant="h2">{Number(out.score).toFixed(4)}</Box></div>}
            {out.scores && <ScoreBars scores={out.scores} />}
            {out.vyomiTrained && <Box variant="small" color="text-status-inactive">vyomiTrained: true. Produced by the small head trained in this simulator, not by a language model.</Box>}
          </SpaceBetween>
        </Container>)}
    </SpaceBetween>
  );
}

export default function TrainingJob({ params }) {
  const id = decodeURIComponent(params.id);
  const [job, setJob] = useState(null), [err, setErr] = useState(null), [stopping, setStopping] = useState(false);
  const timer = useRef();
  const load = async () => {
    try { const j = await api.getCustomizationJob(id); setJob(j); setErr(null); return j; } catch (e) { setErr(e); return null; }
  };
  useEffect(() => {
    let dead = false;
    const loop = async () => { const j = await load(); if (dead) return; const t = trainingOf(j); if (!j || isActive(t?.status) || j.status === "InProgress") timer.current = setTimeout(loop, 1500); };
    loop();
    return () => { dead = true; clearTimeout(timer.current); };
  }, [id]);   // eslint-disable-line react-hooks/exhaustive-deps
  const t = trainingOf(job);
  const stop = async () => { setStopping(true); try { await api.stopCustomizationJob(job.jobArn || id); } catch (e) { setErr(e); } await load(); setStopping(false); };
  if (!job) return <Page title={id}>{err ? <ErrorAlert error={err} header="Could not load the job" /> : <Spinner />}</Page>;
  const running = t ? isActive(t.status) : job.status === "InProgress";
  return (
    <Page title={job.jobName || id} description="Model customization job">
      {err && <ErrorAlert error={err} header="Request failed" />}
      <Alert type="info" data-testid="honest-note">{t ? HONEST : NON_TRAINABLE}</Alert>
      {t && running && isNano() && <Alert type="warning" data-testid="keep-open">{KEEP_TAB_OPEN}</Alert>}
      <Container header={<Header variant="h2" actions={<Button disabled={!running || stopping} loading={stopping} onClick={stop}>Stop job</Button>}>Job overview</Header>}>
        <SpaceBetween size="m">
          <ColumnLayout columns={4} variant="text-grid">
            <Kv label="Status" id="job-status">{jobStatus(t?.status === "Completed" ? "Completed" : t?.status || job.status)}{t && !["Completed", "Failed", "Stopped"].includes(t.status) ? ` (${t.status})` : ""}</Kv>
            <Kv label="Base model">{modelOf(job.baseModelArn)}</Kv>
            <Kv label="Task type">{t ? TASKS.find((x) => x.id === t.taskType)?.label : "Metadata only"}</Kv>
            <Kv label="Engine" id="job-engine">{t?.engine}</Kv>
            <Kv label="Custom model">{job.outputModelName || job.customModelName}</Kv>
            <Kv label="Training rows">{t?.rows || "-"}</Kv>
            <Kv label="Started">{when(t?.startedAt || job.creationTime)}</Kv>
            <Kv label="Ended">{when(t?.endedAt || job.endTime)}</Kv>
          </ColumnLayout>
          {t && <TrainingProgress value={t.progress} status={t.status} label={`${t.status}${t.epochs ? `, epoch ${t.epoch} of ${t.epochs}` : ""}`} />}
          {t?.note && <Box color="text-body-secondary" data-testid="job-note">{t.note}</Box>}
          {job.failureMessage && <Alert type="error">{job.failureMessage}</Alert>}
        </SpaceBetween>
      </Container>
      {t && (
        <ColumnLayout columns={2}>
          <Container header={<Header variant="h2" description="Loss and training accuracy for each epoch">Training metrics</Header>}><TrainingChart metrics={t.metrics} epochs={t.epochs} /></Container>
          <Container header={<Header variant="h2" description="Accuracy on rows the head never trained on">Held-out accuracy vs baseline</Header>}><HeldOutBars heldOut={t.heldOut} /></Container>
        </ColumnLayout>)}
      {t && (
        <Container header={<Header variant="h2">Output</Header>}>
          <ColumnLayout columns={2} variant="text-grid">
            <Kv label="Trained head artifact" id="job-artifact">{t.artifact ? <code>{t.artifact}</code> : "Available when training completes"}</Kv>
            <Kv label="Held-out accuracy">{t.heldOut ? pct(t.heldOut.accuracy) : "-"}</Kv>
          </ColumnLayout>
        </Container>)}
      {t && (
        <Container header={<Header variant="h2" description="Calls InvokeModel on the custom model; the trained head answers, no language model is involved.">Try it</Header>}>
          {t.status === "Completed" ? <TryIt job={job} t={t} /> : <Box color="text-status-inactive" data-testid="try-disabled">Available once training completes.</Box>}
        </Container>)}
    </Page>
  );
}
