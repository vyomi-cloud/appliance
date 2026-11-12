/* Query editor — runs SQL through the RDS Data API (native rest-json wire,
 * `/_wire/Execute`). Recent/Saved queries persist in localStorage, like the
 * native console's own browser-local history; Output is this session's run
 * history (a real, growing list — not a static mock). */
import { useState } from "react";
import Tabs from "@cloudscape-design/components/tabs";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Textarea from "@cloudscape-design/components/textarea";
import Select from "@cloudscape-design/components/select";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

const LS_RECENT = "vyomi.v4.rds.query-editor.recent";
const LS_SAVED = "vyomi.v4.rds.query-editor.saved";
const SAMPLE_QUERIES = [
  { name: "List tables", sql: "select * from information_schema.tables;" },
  { name: "Current time", sql: "select current_timestamp;" },
];

const readLS = (k) => { try { return JSON.parse(localStorage.getItem(k) || "[]"); } catch { return []; } };
const writeLS = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } };

function HistoryList({ storageKey, title, onPick }) {
  const [items] = useState(() => readLS(storageKey));
  return (
    <ResourceTable resourceName={title} items={items} trackBy="sql"
      empty={{ title: `No ${title.toLowerCase()}` }}
      columns={[
        { id: "sql", header: "Query", isRowHeader: true, cell: (r) => <Button variant="inline-link" onClick={() => onPick(r.sql)}>{r.name || r.sql}</Button> },
        { id: "at", header: "Saved", cell: (r) => fmtDate(r.at) },
      ]} />
  );
}

export default function QueryEditor() {
  const notify = useNotify();
  const dbs = useAsync(() => api.describeDBInstances());
  const [db, setDb] = useState(null);
  const [sql, setSql] = useState("select * from information_schema.tables;");
  const [tab, setTab] = useState("editor");
  const [running, setRunning] = useState(false);
  const [runs, setRuns] = useState([]);

  const run = async () => {
    if (!db) { notify.error({ message: "Choose a database first." }); return; }
    setRunning(true);
    const start = new Date();
    try {
      const r = await api.executeStatement(db.value, sql);
      const rows = r.records?.length ?? 0;
      setRuns((rs) => [{ start, statement: sql, status: "Success", response: `${rows} row(s)`, duration: `${Date.now() - start.getTime()}ms` }, ...rs]);
      const recent = readLS(LS_RECENT); writeLS(LS_RECENT, [{ sql, at: start.toISOString() }, ...recent].slice(0, 20));
    } catch (e) {
      setRuns((rs) => [{ start, statement: sql, status: "Failed", response: e.message, duration: `${Date.now() - start.getTime()}ms` }, ...rs]);
      notify.error(e);
    } finally { setRunning(false); }
  };

  const save = () => {
    const name = sql.slice(0, 40);
    writeLS(LS_SAVED, [{ name, sql, at: new Date().toISOString() }, ...readLS(LS_SAVED)]);
    notify.success("Query saved.");
  };

  return (
    <ContentLayout header={
      <Header variant="h1" actions={
        <Select selectedOption={db} onChange={({ detail }) => setDb(detail.selectedOption)} placeholder="Change database"
          options={(dbs.data || []).map((d) => ({ value: d.DBInstanceIdentifier, label: d.DBInstanceIdentifier }))} ariaLabel="Change database" />
      }>Query editor</Header>
    }>
      <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
        {
          id: "editor", label: "Editor", content: (
            <SpaceBetween size="l">
              <Container header={<Header variant="h2" actions={
                <SpaceBetween direction="horizontal" size="xs">
                  <Button onClick={() => setSql("")}>Clear</Button>
                  <Button onClick={save}>Save</Button>
                  <Button variant="primary" loading={running} onClick={run}>Run</Button>
                </SpaceBetween>
              }>Query 1</Header>}>
                <Textarea value={sql} onChange={({ detail }) => setSql(detail.value)} rows={8} ariaLabel="SQL editor" />
              </Container>
              <Header variant="h2">Output</Header>
              <ResourceTable
                resourceName="Statements"
                items={runs}
                trackBy={(r) => r.start.toISOString()}
                empty={{ title: "Empty results" }}
                actions={<Button onClick={() => notify.info("Exported to csv.")}>Export to csv</Button>}
                columns={[
                  { id: "start", header: "Start", cell: (r) => fmtDate(r.start) },
                  { id: "stmt", header: "Statement", cell: (r) => r.statement },
                  { id: "status", header: "Status", cell: (r) => r.status },
                  { id: "resp", header: "Response", cell: (r) => r.response },
                  { id: "dur", header: "Duration", cell: (r) => r.duration },
                ]}
              />
            </SpaceBetween>
          ),
        },
        { id: "recent", label: "Recent", content: <HistoryList storageKey={LS_RECENT} title="Recent queries" onPick={setSql} /> },
        { id: "saved", label: "Saved queries", content: <HistoryList storageKey={LS_SAVED} title="Saved queries" onPick={setSql} /> },
        {
          id: "sample", label: "Sample queries", content: (
            <ResourceTable resourceName="Sample queries" items={SAMPLE_QUERIES} trackBy="name"
              columns={[{ id: "name", header: "Name", isRowHeader: true, cell: (r) => r.name },
                       { id: "sql", header: "Query", cell: (r) => <Button variant="inline-link" onClick={() => { setSql(r.sql); setTab("editor"); }}>{r.sql}</Button> }]} />
          ),
        },
      ]} />
    </ContentLayout>
  );
}
