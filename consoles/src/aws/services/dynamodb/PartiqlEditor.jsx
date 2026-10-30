import { useMemo, useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Button from "@cloudscape-design/components/button";
import Table from "@cloudscape-design/components/table";
import Link from "@cloudscape-design/components/link";
import Box from "@cloudscape-design/components/box";
import Alert from "@cloudscape-design/components/alert";
import { useAsync } from "../../../common/useAsync.js";
import { follow, href } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function PartiqlEditor() {
  const tables = useAsync(() => api.listTables(), []);
  const [statement, setStatement] = useState('SELECT * FROM "table-name"');
  const [view, setView] = useState("Table view");
  const [result, setResult] = useState({ items: null, error: null, running: false });

  const run = async () => {
    setResult({ items: null, error: null, running: true });
    try {
      const r = await api.executeStatement(statement);
      setResult({ items: (r.Items || []).map(api.unmarshalItem), error: null, running: false });
    } catch (e) { setResult({ items: null, error: e, running: false }); }
  };

  const attrs = useMemo(() => {
    const keys = new Set();
    (result.items || []).forEach((it) => Object.keys(it).forEach((k) => keys.add(k)));
    return [...keys];
  }, [result.items]);

  return (
    <ContentLayout header={<Header variant="h1">PartiQL editor</Header>}>
      <SpaceBetween size="l">
        <Table variant="container" items={(tables.data || []).map((n) => ({ n }))} loading={tables.loading}
          header={<Header variant="h2" counter={`(${(tables.data || []).length})`}>Tables</Header>}
          columnDefinitions={[{ id: "name", header: "Name", cell: (r) => <Link href={href("dynamodb", "tables", r.n)} onFollow={follow}>{r.n}</Link> }]}
          empty={<Box textAlign="center" color="inherit"><b>No tables</b></Box>} />

        <Container header={<Header variant="h2" actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => { setStatement(""); setResult({ items: null, error: null, running: false }); }}>Clear</Button>
            <Button variant="primary" onClick={run} loading={result.running}>Run</Button>
          </SpaceBetween>
        }>Query 1</Header>}>
          <FormField label="PartiQL" description='e.g. SELECT * FROM "Music" WHERE Artist = &apos;Alice&apos;'>
            <Textarea rows={6} value={statement} onChange={({ detail }) => setStatement(detail.value)} ariaLabel="PartiQL" />
          </FormField>
        </Container>

        <Container header={<Header variant="h2">Items returned</Header>}>
          <SpaceBetween size="l">
            <FormField label="Results view">
              <RadioGroup value={view} onChange={({ detail }) => setView(detail.value)}
                items={[{ value: "Table view", label: "Table view" }, { value: "JSON view", label: "JSON view" }]} />
            </FormField>
            {result.error && <ErrorAlert error={result.error} />}
            {!result.error && result.items && (
              view === "JSON view" ? (
                <Textarea rows={12} readOnly value={JSON.stringify(result.items, null, 2)} ariaLabel="Results JSON" />
              ) : (
                <Table variant="embedded" items={result.items}
                  header={<Header variant="h3" counter={`(${result.items.length})`}>Results</Header>}
                  columnDefinitions={attrs.map((a) => ({ id: a, header: a, cell: (it) => it[a] === undefined ? "" : String(it[a]) }))}
                  empty={<Box textAlign="center" color="inherit"><b>The statement did not return any results.</b></Box>} />
              )
            )}
            {!result.error && !result.items && !result.running && <Alert type="info" statusIconAriaLabel="Info">Run a PartiQL statement to see results here.</Alert>}
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
