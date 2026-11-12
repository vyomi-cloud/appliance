import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import Container from "@cloudscape-design/components/container";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, fmtDate, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const execArn = (sm, exec) => `arn:aws:states:us-east-1:000000000000:execution:${sm}:${exec}`;
const execStatus = (s) => ({ RUNNING: "in-progress", SUCCEEDED: "success", FAILED: "error", ABORTED: "stopped", TIMED_OUT: "error" }[s] || "pending");

function GraphView({ definitionText, history }) {
  let states = {};
  try { states = JSON.parse(definitionText || "{}").States || {}; } catch { /* malformed definition snapshot */ }
  const entered = history.filter((e) => e.type.endsWith("StateEntered"));
  const exitedNames = new Set(history.filter((e) => e.type.endsWith("StateExited")).map((e) => e.stateExitedEventDetails?.name));
  const path = entered.map((e) => e.stateEnteredEventDetails?.name).filter(Boolean);
  if (!path.length) return <Box color="text-body-secondary" padding="m">No states have run yet.</Box>;
  return (
    <SpaceBetween size="xs">
      {path.map((name, i) => {
        const isLast = i === path.length - 1;
        const ok = exitedNames.has(name);
        const type = isLast && !ok ? "error" : ok ? "success" : "in-progress";
        return (
          <Box key={`${name}-${i}`}>
            <div style={{ border: "1px solid var(--color-border-divider-default, #ccc)", borderRadius: 4, padding: "8px 12px" }}>
              <SpaceBetween direction="horizontal" size="s" alignItems="center">
                <StatusIndicator type={type}>{name}</StatusIndicator>
                <Box color="text-body-secondary" fontSize="body-s">{states[name]?.Type || ""}</Box>
              </SpaceBetween>
            </div>
            {!isLast && <Box textAlign="center" color="text-body-secondary">↓</Box>}
          </Box>
        );
      })}
    </SpaceBetween>
  );
}

export default function ExecutionDetail({ params }) {
  const { name, execName } = params;
  const arn = execArn(name, execName);
  const notify = useNotify();
  const t = useAsync(() => api.describeExecution(arn), [arn]);
  const h = useAsync(() => api.getExecutionHistory(arn), [arn]);
  const sm = useAsync(() => api.describeStateMachineForExecution(arn), [arn]);
  const traceId = (t.data?.traceHeader || "").match(/Root=([^;]+)/)?.[1];
  const trace = useAsync(() => (traceId ? api.getTrace(traceId) : Promise.resolve(null)), [traceId, t.data?.status]);
  const [busy, setBusy] = useState(false);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const d = t.data;

  const stop = async () => {
    setBusy(true);
    try { await api.stopExecution(arn); notify.success("Stopping execution."); t.reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  const redrive = async () => {
    setBusy(true);
    try { await api.redriveExecution(arn); notify.success("Execution redriven."); t.reload(); h.reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={() => { t.reload(); h.reload(); }} iconName="refresh" ariaLabel="Refresh" />
        <Button loading={busy} disabled={d.status !== "RUNNING"} onClick={stop}>Stop execution</Button>
        <Button loading={busy} disabled={!["FAILED", "TIMED_OUT", "ABORTED"].includes(d.status)} onClick={redrive}>Redrive execution</Button>
      </SpaceBetween>
    }>{execName}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={3} items={[
          ["Execution status", <StatusIndicator key="s" type={execStatus(d.status)}>{d.status}</StatusIndicator>],
          ["Start date", fmtDate(d.startDate)],
          ["End date", d.stopDate ? fmtDate(d.stopDate) : "-"],
        ]} />

        <Container header={<Header variant="h2">Graph view</Header>}>
          <GraphView definitionText={sm.data?.definition} history={h.data || []} />
        </Container>

        {traceId && (
          <CapabilityContainer id="aws.states.state-machine.tracing" title="X-Ray trace">
            {trace.data ? (
              <SpaceBetween size="xs">
                <Box>Trace <code>{trace.data.id}</code> - {Number(trace.data.duration).toFixed(3)} s</Box>
                <Table variant="embedded" items={trace.data.segments.flatMap((sg) => [{ n: sg.name, kind: "segment", s: sg, d: sg.end_time - sg.start_time }, ...(sg.subsegments || []).map((x) => ({ n: x.name, kind: x.annotations?.StateType || "subsegment", s: x, d: x.end_time - x.start_time }))])}
                  trackBy="n" columnDefinitions={[
                    { id: "n", header: "Segment", cell: (r) => (r.kind === "segment" ? <b>{r.n}</b> : <span style={{ paddingLeft: 16 }}>{r.n}</span>) },
                    { id: "k", header: "Type", cell: (r) => r.kind },
                    { id: "d", header: "Duration", cell: (r) => `${(r.d * 1000).toFixed(1)} ms` },
                    { id: "f", header: "Result", cell: (r) => <StatusIndicator type={r.s.fault ? "error" : "success"}>{r.s.fault ? "Fault" : "OK"}</StatusIndicator> },
                  ]} />
              </SpaceBetween>
            ) : <Box>{trace.loading ? "Loading trace..." : "The trace is recorded when the execution finishes."}</Box>}
          </CapabilityContainer>
        )}

        <Table
          variant="container"
          items={h.data || []}
          loading={h.loading}
          trackBy="id"
          header={<Header variant="h2" counter={`(${(h.data || []).length})`}>Execution event history</Header>}
          columnDefinitions={[
            { id: "id", header: "ID", cell: (e) => e.id },
            { id: "type", header: "Type", cell: (e) => e.type },
            { id: "step", header: "Step", cell: (e) => e.stateEnteredEventDetails?.name || e.stateExitedEventDetails?.name || "-" },
            { id: "ts", header: "Timestamp", cell: (e) => fmtDate(e.timestamp) },
          ]}
          empty={<Box textAlign="center" color="inherit"><b>No events</b></Box>}
        />

        <KeyValue title="Input and output" columns={2} items={[
          ["Input", <Box variant="code" key="in"><pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{d.input}</pre></Box>],
          ["Output", <Box variant="code" key="out"><pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{d.output || (d.error ? `${d.error}: ${d.cause || ""}` : "-")}</pre></Box>],
        ]} />
      </SpaceBetween>
    </ContentLayout>
  );
}
