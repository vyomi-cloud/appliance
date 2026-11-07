import { useEffect, useState } from "react";
import { Button, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Textarea } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import { listWorkspaces, runLogQuery } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";

const DEFAULT_QUERY = "AzureActivity\n| take 20";
/** Other blades (Activity log "Insights", Change Analysis "Open query") hand a KQL query over through sessionStorage. */
const takeHandoff = () => { try { const q = sessionStorage.getItem("vyomi.logs.query"); sessionStorage.removeItem("vyomi.logs.query"); return q; } catch { return null; } };
export const openInLogs = (kql) => { try { sessionStorage.setItem("vyomi.logs.query", kql); } catch { /* storage blocked */ } location.hash = "#/monitor/logs"; };

export default function Logs() {
  const [workspaces, setWorkspaces] = useState(null);
  const [workspace, setWorkspace] = useState("");
  const [query, setQuery] = useState(() => takeHandoff() || DEFAULT_QUERY);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    listWorkspaces().then((ws) => { setWorkspaces(ws); setWorkspace(ws[0]?.id || ""); }).catch(() => setWorkspaces([]));
  }, []);

  const run = async () => {
    const ws = workspaces.find((w) => w.id === workspace);
    if (!ws) return;
    setRunning(true); setError(null);
    try {
      setResult(await runLogQuery(ws.resourceGroup, ws.name, query));
    } catch (e) {
      setError(e); setResult(null);
    } finally {
      setRunning(false);
    }
  };

  const table = result?.tables?.[0];

  return (
    <MonitorShell active="logs">
      <CapabilityContainer id="azure.monitor.log_analytics_workspaces" title="Welcome to Log Analytics">
        {workspaces === null ? <Loading /> : (
          <p>
            Your subscription has {workspaces.length} Log Analytics workspace{workspaces.length === 1 ? "" : "s"}.{" "}
            <a href="#/monitor/loganalyticsworkspaces">Manage workspaces</a>
          </p>
        )}
        <Button appearance="primary" as="a" href="#/monitor/loganalyticsworkspaces">Create a Log Analytics workspace</Button>
      </CapabilityContainer>

      <CapabilityContainer id="azure.monitor.log_query" title="Run a query">
        {workspaces === null ? <Loading /> : !workspaces.length ? (
          <p>No Log Analytics workspace yet. <a href="#/monitor/createloganalyticsworkspace">Create one</a> first.</p>
        ) : (
          <>
            <div className="vy-form-row"><label>Scope</label>
              <Select value={workspace} onChange={(_, d) => setWorkspace(d.value)} aria-label="Log Analytics workspace">
                {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </Select>
            </div>
            <Textarea value={query} onChange={(_, d) => setQuery(d.value)} rows={4} resize="vertical"
              style={{ width: "100%", fontFamily: "monospace" }} aria-label="KQL query" />
            <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
              <Button appearance="primary" disabled={running || !workspace} onClick={run}>Run</Button>
              <span style={{ fontSize: 12, marginLeft: 12, opacity: 0.8 }}>KQL: where, extend, project, summarize (count/sum/avg/min/max/dcount/countif by col or bin()), top, order by, take, count, distinct; ago(), strcat(), iff() ...</span>
            </div>
            <ErrorBar error={error} title="Query failed" />
            {table && (table.rows.length ? (
              <Table size="small" aria-label="Query results">
                <TableHeader><TableRow>{table.columns.map((c) => <TableHeaderCell key={c.name}>{c.name}</TableHeaderCell>)}</TableRow></TableHeader>
                <TableBody>
                  {table.rows.map((row, i) => (
                    <TableRow key={i}>{row.map((cell, j) => <TableCell key={j}>{cell === null || cell === undefined ? "" : String(cell)}</TableCell>)}</TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : <p>No results found.</p>)}
          </>
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
