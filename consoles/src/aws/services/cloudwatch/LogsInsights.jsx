import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Multiselect from "@cloudscape-design/components/multiselect";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const DEFAULT_QUERY = "fields @timestamp, @message, @logStream, @log | sort @timestamp desc | limit 10000";

function LogsTab() {
  const notify = useNotify();
  const groups = useAsync(() => api.describeLogGroups({}), []);
  const [lang, setLang] = useState("Logs Insights QL");
  const [selected, setSelected] = useState([]);
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [results, setResults] = useState(null);

  const run = async () => {
    if (!selected.length) { setError(new Error("Select at least one log group.")); return; }
    setBusy(true); setError(null);
    try {
      const now = Math.floor(Date.now() / 1000);
      const queryId = await api.startQuery({ logGroupNames: selected.map((o) => o.value), startTime: now - 3600, endTime: now, queryString: query });
      const r = await api.getQueryResults(queryId);
      setResults(r.results || []);
    } catch (e) { setError(e); notify.error(e); } finally { setBusy(false); }
  };

  const fields = results?.length ? results[0].map((c) => c.field) : [];

  return (
    <SpaceBetween size="l">
      {error && <ErrorAlert error={error} />}
      <Container header={<Header variant="h2" actions={<SpaceBetween direction="horizontal" size="xs"><Button onClick={run} loading={busy} variant="primary">Run query</Button><Button disabled>Save</Button><Button disabled>History</Button></SpaceBetween>}>Query</Header>}>
        <SpaceBetween size="l">
          <FormField label="Query language">
            <RadioGroup value={lang} onChange={({ detail }) => setLang(detail.value)}
              items={[{ value: "Logs Insights QL", label: "Logs Insights QL" }, { value: "OpenSearch PPL", label: "OpenSearch PPL", disabled: true }, { value: "OpenSearch SQL", label: "OpenSearch SQL", disabled: true }]}
              ariaLabel="Query language" />
          </FormField>
          <FormField label="Selection criteria">
            <Multiselect placeholder="Select log groups" selectedOptions={selected} onChange={({ detail }) => setSelected(detail.selectedOptions)}
              options={(groups.data || []).map((g) => ({ label: g.logGroupName, value: g.logGroupName }))} ariaLabel="Selection criteria" />
          </FormField>
          <FormField label="Query" stretch>
            <Textarea value={query} onChange={({ detail }) => setQuery(detail.value)} rows={6} ariaLabel="Query" />
          </FormField>
        </SpaceBetween>
      </Container>
      {results !== null && (
        <Table
          items={results.map((row, i) => ({ id: i, ...Object.fromEntries(row.map((c) => [c.field, c.value])) }))}
          columnDefinitions={fields.filter((f) => f !== "@ptr").map((f) => ({ id: f, header: f, cell: (r) => r[f] }))}
          empty={<Box textAlign="center" color="inherit">No results</Box>}
          header={<Header variant="h3" counter={`(${results.length})`}>Results</Header>}
        />
      )}
    </SpaceBetween>
  );
}

export default function LogsInsights() {
  return (
    <ContentLayout header={<Header variant="h1">Logs Insights</Header>}>
      <Tabs tabs={[
        { id: "logs", label: "Logs", content: <LogsTab /> },
        { id: "patterns", label: "Patterns", content: <CapabilityContainer id="aws.cloudwatch.logs.patterns-visualization" title="Patterns" /> },
        { id: "visualization", label: "Visualization", content: <CapabilityContainer id="aws.cloudwatch.logs.patterns-visualization" title="Visualization" /> },
      ]} />
    </ContentLayout>
  );
}
