import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Checkbox from "@cloudscape-design/components/checkbox";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import RadioGroup from "@cloudscape-design/components/radio-group";
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

const DATA_IDENTIFIERS = ["EmailAddress", "CreditCardNumber", "Ssn-US", "AwsSecretKey"];
const dataIdentifierArn = (id) => `arn:aws:dataprotection::aws:data-identifier/${id}`;

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
          <FormField label="Destination ARN" description="A Lambda function or Kinesis stream destination really receives matched events; a Firehose destination is only counted.">
            <Textarea value={destinationArn} onChange={({ detail }) => setDestinationArn(detail.value)} ariaLabel="Destination ARN" />
          </FormField>
        </SpaceBetween>
      </Modal>
    </Container>
  );
}

function DataProtectionTab({ group, onChanged }) {
  const notify = useNotify();
  const t = useAsync(() => api.getDataProtectionPolicy(group).catch((e) => (e.code === "ResourceNotFoundException" ? null : Promise.reject(e))), [group]);
  const current = t.data?.policyDocument;
  const currentIds = new Set((current?.Statement || []).flatMap((s) => s.DataIdentifier || []).map((a) => a.split("/").pop()));
  const masking = (current?.Statement || []).some((s) => s.Operation?.Deidentify);
  const [ids, setIds] = useState(null);
  const [mode, setMode] = useState(null);
  const selectedIds = ids ?? [...currentIds];
  const selectedMode = mode ?? (masking ? "mask" : "audit");

  const save = async () => {
    if (!selectedIds.length) return;
    const dataIdentifiers = selectedIds.map(dataIdentifierArn);
    const statements = [{ Sid: "audit-policy", DataIdentifier: dataIdentifiers, Operation: { Audit: { FindingsDestination: {} } } }];
    if (selectedMode === "mask") statements.push({ Sid: "redact-policy", DataIdentifier: dataIdentifiers, Operation: { Deidentify: { MaskConfig: {} } } });
    await api.putDataProtectionPolicy(group, { Name: "data-protection-policy", Version: "2021-06-01", Statement: statements });
    notify.success("Data protection policy saved.");
    setIds(null); setMode(null); t.reload(); onChanged?.();
  };

  const remove = async () => {
    await api.deleteDataProtectionPolicy(group);
    notify.success("Data protection policy removed.");
    setIds(null); setMode(null); t.reload(); onChanged?.();
  };

  return (
    <CapabilityContainer id="aws.cloudwatch.logs.data-protection" title="Data protection"
      actions={current && <Button onClick={remove}>Deactivate</Button>}>
      {t.loading ? <Spinner /> : (
        <SpaceBetween size="l">
          <FormField label="Data identifiers to find" description="Matched against @message when events are ingested.">
            <SpaceBetween size="xs">
              {DATA_IDENTIFIERS.map((id) => (
                <Checkbox key={id} checked={selectedIds.includes(id)}
                  onChange={({ detail }) => setIds((detail.checked ? [...selectedIds, id] : selectedIds.filter((x) => x !== id)))}>
                  {id}
                </Checkbox>
              ))}
            </SpaceBetween>
          </FormField>
          <FormField label="Action">
            <RadioGroup value={selectedMode} onChange={({ detail }) => setMode(detail.value)}
              items={[{ value: "audit", label: "Audit — count findings, don't change the data" }, { value: "mask", label: "Audit and mask — findings are replaced with asterisks as they're ingested" }]}
              ariaLabel="Data protection action" />
          </FormField>
          <Button variant="primary" onClick={save} disabled={!selectedIds.length}>Activate data protection</Button>
        </SpaceBetween>
      )}
    </CapabilityContainer>
  );
}

function FieldIndexesTab({ group }) {
  const notify = useNotify();
  const t = useAsync(() => api.getIndexPolicy(group).catch((e) => (e.code === "ResourceNotFoundException" ? [] : Promise.reject(e))), [group]);
  const [text, setText] = useState(null);
  const current = (t.data || []).join(", ");

  const save = async () => {
    const fields = (text ?? current).split(",").map((f) => f.trim()).filter(Boolean);
    await api.putIndexPolicy(group, fields);
    notify.success("Field index policy saved.");
    setText(null); t.reload();
  };

  const remove = async () => {
    await api.deleteIndexPolicy(group);
    notify.success("Field index policy removed.");
    setText(null); t.reload();
  };

  return (
    <CapabilityContainer id="aws.cloudwatch.logs.field-indexes" title="Field indexes"
      actions={(t.data || []).length > 0 && <Button onClick={remove}>Delete policy</Button>}>
      {t.loading ? <Spinner /> : (
        <SpaceBetween size="l">
          <FormField label="Indexed fields" description="Comma-separated Logs Insights field names, e.g. requestId, statusCode.">
            <Input value={text ?? current} onChange={({ detail }) => setText(detail.value)} ariaLabel="Indexed fields" />
          </FormField>
          <Button variant="primary" onClick={save} disabled={!(text ?? current).trim()}>Save field index policy</Button>
        </SpaceBetween>
      )}
    </CapabilityContainer>
  );
}

const TRANSFORMER_EXAMPLE = JSON.stringify([{ parseJSON: { source: "@message" } }, { addKeys: { entries: [{ key: "env", value: "prod" }] } }], null, 1);

function TransformerTab({ group }) {
  const notify = useNotify();
  const t = useAsync(() => api.getTransformer(group).catch((e) => (e.code === "ResourceNotFoundException" ? null : Promise.reject(e))), [group]);
  const [text, setText] = useState(null);
  const [jsonErr, setJsonErr] = useState(null);
  const current = text ?? (t.data ? JSON.stringify(t.data, null, 1) : TRANSFORMER_EXAMPLE);

  const save = async () => {
    let cfg;
    try { cfg = JSON.parse(current); } catch (e) { setJsonErr(`Not valid JSON: ${e.message}`); return; }
    setJsonErr(null);
    await api.putTransformer(group, cfg);
    notify.success("Transformer saved.");
    setText(null); t.reload();
  };

  const remove = async () => {
    await api.deleteTransformer(group);
    notify.success("Transformer removed.");
    setText(null); t.reload();
  };

  return (
    <CapabilityContainer id="aws.cloudwatch.logs.transformer" title="Transformer" actions={t.data && <Button onClick={remove}>Delete transformer</Button>}>
      {t.loading ? <Spinner /> : (
        <SpaceBetween size="l">
          {jsonErr && <ErrorAlert error={new Error(jsonErr)} />}
          <FormField label="Transformer config" description="A JSON array of processors (parseJSON, addKeys, deleteKeys, renameKeys), run in order on every PutLogEvents.">
            <Textarea value={current} onChange={({ detail }) => setText(detail.value)} rows={8} ariaLabel="Transformer config" />
          </FormField>
          <Button variant="primary" onClick={save}>Save transformer</Button>
        </SpaceBetween>
      )}
    </CapabilityContainer>
  );
}

function ContributorInsightsTab({ group }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeInsightRules({}), []);
  const rules = (t.data || []).filter((r) => { try { return JSON.parse(r.Definition).LogGroupNames?.includes(group); } catch { return false; } });
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [keys, setKeys] = useState("$.ip");
  const [valueOf, setValueOf] = useState("");
  const [report, setReport] = useState(null);
  const [reportFor, setReportFor] = useState(null);

  const create = async () => {
    const definition = {
      Schema: { Name: "CloudWatchLogRule", Version: 1 }, LogGroupNames: [group], LogFormat: "JSON",
      Contribution: { Keys: keys.split(",").map((k) => k.trim()).filter(Boolean), ...(valueOf ? { ValueOf: valueOf } : {}) },
      AggregateOn: valueOf ? "Sum" : "Count",
    };
    await api.putInsightRule(name, definition);
    notify.success(`Contributor Insights rule ${name} created.`);
    setAdding(false); setName(""); t.reload();
  };

  const runReport = async (ruleName) => {
    const now = Math.floor(Date.now() / 1000);
    const r = await api.getInsightRuleReport(ruleName, now - 3600, now);
    setReportFor(ruleName); setReport(r);
  };

  return (
    <CapabilityContainer id="aws.cloudwatch.logs.contributor-insights" title="Contributor Insights" actions={<Button onClick={() => setAdding(true)}>Create rule</Button>}>
      <SpaceBetween size="l">
        <Table
          variant="embedded"
          items={rules}
          loading={t.loading}
          trackBy="Name"
          columnDefinitions={[
            { id: "name", header: "Rule name", cell: (r) => r.Name },
            { id: "state", header: "State", cell: (r) => r.State },
            { id: "report", header: "", cell: (r) => <Button variant="inline-link" onClick={() => runReport(r.Name)}>Run report (last hour)</Button> },
            { id: "del", header: "", cell: (r) => <Button variant="icon" iconName="remove" ariaLabel={`Delete ${r.Name}`} onClick={async () => { await api.deleteInsightRules([r.Name]); t.reload(); }} /> },
          ]}
          empty={<Box textAlign="center" color="inherit">No Contributor Insights rules for this log group.</Box>}
        />
        {reportFor && (
          <Table
            variant="embedded"
            items={(report?.Contributors || []).map((c, i) => ({ id: i, keys: c.Keys.join(", "), value: c.ApproximateAggregateValue }))}
            columnDefinitions={[{ id: "keys", header: report?.KeyLabels?.join(", ") || "Keys", cell: (r) => r.keys }, { id: "value", header: report?.AggregationStatistic || "Value", cell: (r) => r.value }]}
            empty={<Box textAlign="center" color="inherit">No contributors in the last hour.</Box>}
            header={<Header variant="h3">{reportFor} — top contributors</Header>}
          />
        )}
      </SpaceBetween>
      <Modal visible={adding} onDismiss={() => setAdding(false)} header="Create Contributor Insights rule" footer={<Box float="right"><Button variant="primary" disabled={!name || !keys} onClick={create}>Create rule</Button></Box>}>
        <SpaceBetween size="l">
          <FormField label="Rule name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Rule name" /></FormField>
          <FormField label="Contribution keys" description="Comma-separated JSONPath into each log event, e.g. $.ip, $.userAgent.">
            <Input value={keys} onChange={({ detail }) => setKeys(detail.value)} ariaLabel="Contribution keys" />
          </FormField>
          <FormField label="Value of (optional)" description="JSONPath to sum instead of counting occurrences.">
            <Input value={valueOf} onChange={({ detail }) => setValueOf(detail.value)} ariaLabel="Value of" />
          </FormField>
        </SpaceBetween>
      </Modal>
    </CapabilityContainer>
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
          { id: "ci", label: "Contributor Insights", content: <ContributorInsightsTab group={name} /> },
          { id: "dataprotection", label: "Data protection", content: <DataProtectionTab group={name} onChanged={t.reload} /> },
          { id: "fieldindexes", label: "Field indexes", content: <FieldIndexesTab group={name} /> },
          { id: "transformer", label: "Transformer", content: <TransformerTab group={name} /> },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={deleting} onDismiss={() => setDeleting(false)} resourceType="log group" names={[name]}
        onConfirm={async () => { await api.deleteLogGroup(name); notify.success(`Log group ${name} deleted.`); navigate("cloudwatch", "logs"); }} />
    </ContentLayout>
  );
}
