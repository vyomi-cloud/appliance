import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import TagEditor from "@cloudscape-design/components/tag-editor";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

const TAG_I18N = {
  keyHeader: "Key", valueHeader: "Value", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo",
  undoPrompt: "Removed upon saving", loading: "Loading tags", keyPlaceholder: "Key", valuePlaceholder: "Value",
  emptyTags: "No tags are associated with this log group.", emptyKeyError: "You must specify a tag key",
  maxKeyCharLengthError: "128 character limit.", maxValueCharLengthError: "256 character limit.",
  duplicateKeyError: "Unique key required.", invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.", awsPrefixError: "Cannot start with aws:",
  tagLimit: (a) => `You can add up to ${a} more tags.`, tagLimitReached: () => "Tag limit reached.", tagLimitExceeded: () => "Tag limit exceeded.",
};

function StreamsTab({ group, reload }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeLogStreams(group), [group]);
  const [selected, setSelected] = useState([]);
  const [deleting, setDeleting] = useState(false);
  return (
    <Container header={<Header variant="h2" counter={`(${(t.data || []).length})`} actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button iconName="refresh" ariaLabel="Refresh" onClick={t.reload} />
        <Button disabled={!selected.length} onClick={() => setDeleting(true)}>Delete</Button>
        <Button href={href("cloudwatch", "logs", group, "streams", "create")} onFollow={follow}>Create log stream</Button>
      </SpaceBetween>
    }>Log streams</Header>}>
      <Table
        variant="embedded"
        items={t.data || []}
        loading={t.loading}
        trackBy="logStreamName"
        selectionType="multi"
        selectedItems={selected}
        onSelectionChange={({ detail }) => setSelected(detail.selectedItems)}
        columnDefinitions={[
          { id: "name", header: "Log stream", cell: (s) => <Link href={href("cloudwatch", "logs", group, "streams", s.logStreamName)} onFollow={follow}>{s.logStreamName}</Link> },
          { id: "last", header: "Last event time", cell: (s) => (s.lastEventTimestamp ? fmtDate(s.lastEventTimestamp) : "No events") },
        ]}
        empty={<Box textAlign="center" color="inherit">No log streams</Box>}
      />
      <DeleteModal visible={deleting} onDismiss={() => setDeleting(false)} resourceType="log stream" names={selected.map((s) => s.logStreamName)}
        onConfirm={async () => { await Promise.all(selected.map((s) => api.deleteLogStream(group, s.logStreamName))); notify.success("Log streams deleted."); setSelected([]); t.reload(); }} />
    </Container>
  );
}

function TagsTab({ group }) {
  const notify = useNotify();
  const t = useAsync(() => api.listTagsLogGroup(group), [group]);
  const [tags, setTags] = useState(null);
  const current = tags ?? Object.entries(t.data || {}).map(([key, value]) => ({ key, value }));
  const save = async () => {
    const existing = t.data || {};
    const keep = Object.fromEntries(current.filter((x) => x.key).map((x) => [x.key, x.value]));
    const removed = Object.keys(existing).filter((k) => !(k in keep));
    if (Object.keys(keep).length) await api.tagLogGroup(group, keep);
    if (removed.length) await api.untagLogGroup(group, removed);
    notify.success("Tags saved.");
    setTags(null); t.reload();
  };
  return (
    <Container header={<Header variant="h2">Tags</Header>}>
      <SpaceBetween size="l">
        <TagEditor tags={current} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} />
        <Button onClick={save}>Save changes</Button>
      </SpaceBetween>
    </Container>
  );
}

function MetricFiltersTab({ group }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeMetricFilters(group), [group]);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [pattern, setPattern] = useState("");
  const [metricName, setMetricName] = useState("");
  const [metricNamespace, setMetricNamespace] = useState(`LogMetrics/${group}`);

  const create = async () => {
    await api.putMetricFilter(group, name, pattern, [{ metricName, metricNamespace, metricValue: "1", defaultValue: "0" }]);
    notify.success(`Metric filter ${name} created.`);
    setAdding(false); setName(""); setPattern(""); setMetricName(""); t.reload();
  };

  return (
    <Container header={<Header variant="h2" counter={`(${(t.data || []).length})`} actions={<Button onClick={() => setAdding(true)}>Create metric filter</Button>}>Metric filters</Header>}>
      <Table
        variant="embedded"
        items={t.data || []}
        loading={t.loading}
        trackBy="filterName"
        columnDefinitions={[
          { id: "name", header: "Filter name", cell: (f) => f.filterName },
          { id: "pattern", header: "Filter pattern", cell: (f) => f.filterPattern || "(match all)" },
          { id: "metric", header: "Metric", cell: (f) => f.metricTransformations?.map((x) => `${x.metricNamespace}/${x.metricName}`).join(", ") },
          { id: "del", header: "", cell: (f) => <Button variant="icon" iconName="remove" ariaLabel={`Delete ${f.filterName}`} onClick={async () => { await api.deleteMetricFilter(group, f.filterName); t.reload(); }} /> },
        ]}
        empty={<Box textAlign="center" color="inherit">No metric filters</Box>}
      />
      <Modal visible={adding} onDismiss={() => setAdding(false)} header="Create metric filter" footer={<Box float="right"><Button variant="primary" disabled={!name || !metricName} onClick={create}>Create metric filter</Button></Box>}>
        <SpaceBetween size="l">
          <FormField label="Filter name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Filter name" /></FormField>
          <FormField label="Filter pattern"><Input value={pattern} onChange={({ detail }) => setPattern(detail.value)} ariaLabel="Filter pattern" /></FormField>
          <FormField label="Metric namespace"><Input value={metricNamespace} onChange={({ detail }) => setMetricNamespace(detail.value)} ariaLabel="Metric namespace" /></FormField>
          <FormField label="Metric name"><Input value={metricName} onChange={({ detail }) => setMetricName(detail.value)} ariaLabel="Metric name" /></FormField>
        </SpaceBetween>
      </Modal>
    </Container>
  );
}

function SubscriptionFiltersTab({ group }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeSubscriptionFilters(group), [group]);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [pattern, setPattern] = useState("");
  const [destinationArn, setDestinationArn] = useState("");

  const create = async () => {
    await api.putSubscriptionFilter(group, name, pattern, destinationArn);
    notify.success(`Subscription filter ${name} created.`);
    setAdding(false); setName(""); setPattern(""); setDestinationArn(""); t.reload();
  };

  return (
    <Container header={<Header variant="h2" counter={`(${(t.data || []).length})`} actions={<Button onClick={() => setAdding(true)}>Create</Button>}>Subscription filters</Header>}>
      <Table
        variant="embedded"
        items={t.data || []}
        loading={t.loading}
        trackBy="filterName"
        columnDefinitions={[
          { id: "name", header: "Filter name", cell: (f) => f.filterName },
          { id: "dest", header: "Destination", cell: (f) => f.destinationArn },
          { id: "del", header: "", cell: (f) => <Button variant="icon" iconName="remove" ariaLabel={`Delete ${f.filterName}`} onClick={async () => { await api.deleteSubscriptionFilter(group, f.filterName); t.reload(); }} /> },
        ]}
        empty={<Box textAlign="center" color="inherit">No subscription filters</Box>}
      />
      <Modal visible={adding} onDismiss={() => setAdding(false)} header="Create subscription filter" footer={<Box float="right"><Button variant="primary" disabled={!name || !destinationArn} onClick={create}>Create</Button></Box>}>
        <SpaceBetween size="l">
          <FormField label="Filter name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Filter name" /></FormField>
          <FormField label="Filter pattern"><Input value={pattern} onChange={({ detail }) => setPattern(detail.value)} ariaLabel="Filter pattern" /></FormField>
          <FormField label="Destination ARN"><Textarea value={destinationArn} onChange={({ detail }) => setDestinationArn(detail.value)} ariaLabel="Destination ARN" /></FormField>
        </SpaceBetween>
      </Modal>
    </Container>
  );
}

export default function LogGroupDetail({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [deleting, setDeleting] = useState(false);
  const t = useAsync(() => api.describeLogGroups({ logGroupNamePrefix: name }).then((gs) => gs.find((g) => g.logGroupName === name)), [name]);

  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error || !t.data) return <ErrorAlert error={t.error || new Error(`Log group ${name} not found`)} />;
  const g = t.data;

  return (
    <ContentLayout header={
      <Header variant="h1" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={t.reload} />
          <ButtonDropdown items={[{ id: "delete", text: "Delete log group" }]} onItemClick={({ detail }) => detail.id === "delete" && setDeleting(true)}>Actions</ButtonDropdown>
          <Button onClick={() => navigate("cloudwatch", "logs-insights")}>View in Logs Insights</Button>
          <Button onClick={() => navigate("cloudwatch", "live-tail")}>Start tailing</Button>
          <Select selectedOption={null} placeholder="Search log group" onChange={() => {}} options={[]} ariaLabel="Search log group" />
        </SpaceBetween>
      }>{name}</Header>
    }>
      <SpaceBetween size="l">
        <KeyValue title="Log group details" columns={3} items={[
          ["Log class", { STANDARD: "Standard", INFREQUENT_ACCESS: "Infrequent Access", DELIVERY: "Delivery" }[g.logGroupClass] || g.logGroupClass],
          ["ARN", g.arn], ["Creation time", fmtDate(g.creationTime)],
          ["Retention", g.retentionInDays ? `${g.retentionInDays} days` : "Never expire"], ["Stored bytes", fmtBytes(g.storedBytes)],
          ["Metric filters", g.metricFilterCount ?? 0], ["Subscription filters", "-"], ["Contributor Insights rules", "-"],
          ["KMS key ID", g.kmsKeyId || "-"], ["Deletion protection", g.deletionProtectionEnabled ? "Enabled" : "Disabled"],
        ]} />
        <Tabs tabs={[
          { id: "streams", label: "Log streams", content: <StreamsTab group={name} /> },
          { id: "tags", label: "Tags", content: <TagsTab group={name} /> },
          { id: "anomaly", label: "Anomaly detection", content: <CapabilityContainer id="aws.cloudwatch.logs.anomaly-detection" title="Anomaly detection" /> },
          { id: "metricfilters", label: "Metric filters", content: <MetricFiltersTab group={name} /> },
          { id: "subfilters", label: "Subscription filters", content: <SubscriptionFiltersTab group={name} /> },
          { id: "ci", label: "Contributor Insights", content: <CapabilityContainer id="aws.cloudwatch.logs.contributor-insights" title="Contributor Insights" /> },
          { id: "dataprotection", label: "Data protection", content: <CapabilityContainer id="aws.cloudwatch.logs.data-protection" title="Data protection" /> },
          { id: "fieldindexes", label: "Field indexes", content: <CapabilityContainer id="aws.cloudwatch.logs.field-indexes" title="Field indexes" /> },
          { id: "transformer", label: "Transformer", content: <CapabilityContainer id="aws.cloudwatch.logs.transformer" title="Transformer" /> },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={deleting} onDismiss={() => setDeleting(false)} resourceType="log group" names={[name]}
        onConfirm={async () => { await api.deleteLogGroup(name); notify.success(`Log group ${name} deleted.`); navigate("cloudwatch", "logs"); }} />
    </ContentLayout>
  );
}
