/* IAM > Event history: CloudTrail-style IAM / STS management events (and gate denials) from GET /api/iam/aws/events. Cloudscape-native. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import { EVENT_COPY, OUTCOMES, OUTCOME_LABEL, eventTime, shortPrincipal } from "../../../common/iamEvents.js";
import { useIamEvents } from "../../../common/iamEventsHooks.js";

const CLOUD = "aws";
const STATUS = { success: "success", denied: "error", error: "error", would_deny: "warning" };

export default function EventHistory() {
  const [f, setF] = useState({ name: "", principal: "", resource: "", outcome: "all", readOnly: "all", scope: "iam" });
  const [draft, setDraft] = useState(f);
  const ev = useIamEvents(CLOUD, f);
  const copy = EVENT_COPY[CLOUD];
  const rows = ev.data?.events || [];
  return (
    <ContentLayout header={<Header variant="h1" description={copy.info}>{copy.title}</Header>}>
      <SpaceBetween size="l">
        {ev.error && <Alert type="error" header="Could not load events">{ev.error.message}</Alert>}
        <Table data-testid="iam-events-table" variant="container" items={rows} trackBy="id" loading={ev.loading} loadingText="Loading events"
          header={<Header variant="h2" counter={ev.data ? `(${ev.data.total})` : ""}
            actions={<SpaceBetween direction="horizontal" size="xs">
              <Button iconName="refresh" onClick={ev.reload} ariaLabel="Refresh events" />
              <Button iconName="download" href={ev.api.exportUrl(f, "csv")} target="_blank" ariaLabel="Export events as CSV">Export CSV</Button>
              <Button href={ev.api.exportUrl(f, "json")} target="_blank">Export JSON</Button></SpaceBetween>}>Events</Header>}
          filter={<SpaceBetween direction="horizontal" size="xs">
            <Input value={draft.name} placeholder={copy.name} ariaLabel="Filter by event name" onChange={({ detail }) => setDraft({ ...draft, name: detail.value })} onKeyDown={(e) => e.detail.key === "Enter" && setF(draft)} />
            <Input value={draft.principal} placeholder="User name" ariaLabel="Filter by user name" onChange={({ detail }) => setDraft({ ...draft, principal: detail.value })} onKeyDown={(e) => e.detail.key === "Enter" && setF(draft)} />
            <Input value={draft.resource} placeholder={copy.resource} ariaLabel="Filter by resource name" onChange={({ detail }) => setDraft({ ...draft, resource: detail.value })} onKeyDown={(e) => e.detail.key === "Enter" && setF(draft)} />
            <Select selectedOption={{ value: draft.outcome, label: draft.outcome === "all" ? "All outcomes" : OUTCOME_LABEL[draft.outcome] }} ariaLabel="Filter by outcome"
              options={[{ value: "all", label: "All outcomes" }, ...OUTCOMES.map((o) => ({ value: o, label: OUTCOME_LABEL[o] }))]} onChange={({ detail }) => { const n = { ...draft, outcome: detail.selectedOption.value }; setDraft(n); setF(n); }} />
            <Select selectedOption={{ value: draft.readOnly, label: { all: "Read and write", true: "Read-only", false: "Write only" }[draft.readOnly] }} ariaLabel="Filter by read-only"
              options={[{ value: "all", label: "Read and write" }, { value: "true", label: "Read-only" }, { value: "false", label: "Write only" }]} onChange={({ detail }) => { const n = { ...draft, readOnly: detail.selectedOption.value }; setDraft(n); setF(n); }} />
            <Button onClick={() => setF(draft)}>Apply</Button></SpaceBetween>}
          empty={<Box textAlign="center" color="inherit">No events match. IAM and STS calls made through the API, CLI or console appear here.</Box>}
          columnDefinitions={[
            { id: "time", header: "Event time", cell: (r) => eventTime(r), width: 200 },
            { id: "name", header: copy.name, cell: (r) => r.name },
            { id: "user", header: "User name", cell: (r) => shortPrincipal(r.principal) || "-" },
            { id: "out", header: "Outcome", cell: (r) => <StatusIndicator type={STATUS[r.outcome] || "info"}>{r.errorCode || OUTCOME_LABEL[r.outcome] || r.outcome}</StatusIndicator> },
            { id: "src", header: "Event source", cell: (r) => r.native?.EventSource || r.service },
            { id: "res", header: copy.resource, cell: (r) => r.resource || "-" },
            { id: "raw", header: "Event record", cell: (r) => <ExpandableSection headerText="View">{<pre style={{ margin: 0, maxWidth: 520, overflow: "auto", fontSize: 12 }}>{JSON.stringify(r.native || r, null, 2)}</pre>}</ExpandableSection> },
          ]} />
        {ev.data?.truncated && <Alert type="info">Showing the most recent {rows.length} matching events. Narrow the filters or export for the full set.</Alert>}
      </SpaceBetween>
    </ContentLayout>
  );
}
