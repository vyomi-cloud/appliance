import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import TagEditor from "@cloudscape-design/components/tag-editor";
import Textarea from "@cloudscape-design/components/textarea";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, KeyValue, NotSimulatedContainer, Status } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ruleType } from "./Rules.jsx";
import * as api from "./api.js";

function EventPatternTab({ rule, reload }) {
  const notify = useNotify();
  const [text, setText] = useState(rule.EventPattern || "{}");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      JSON.parse(text);
      await api.putRule({ Name: rule.Name, EventBusName: rule.EventBusName, EventPattern: text, State: rule.State, Description: rule.Description });
      notify.success("Event pattern updated."); reload();
    } catch (e) { notify.error(e instanceof SyntaxError ? new Error("Must be valid JSON.") : e); } finally { setBusy(false); }
  };
  return (
    <Container header={<Header variant="h2">Event pattern</Header>}>
      <SpaceBetween size="l">
        <Textarea value={text} onChange={({ detail }) => setText(detail.value)} rows={10} ariaLabel="Event pattern" />
        <Box float="left"><Button loading={busy} onClick={save}>Save</Button></Box>
      </SpaceBetween>
    </Container>
  );
}

function TargetsTab({ rule, reload }) {
  const notify = useNotify();
  const { data: targets = [], reload: reloadTargets } = useAsync(() => api.listTargetsByRule(rule.Name, rule.EventBusName), [rule.Name]);
  const { data: options = [] } = useAsync(() => api.listAllTargets());
  const [sel, setSel] = useState([]);
  const [adding, setAdding] = useState(null);
  const add = async () => {
    if (!adding) return;
    await api.putTargets(rule.Name, rule.EventBusName, [{ Id: `t${Date.now().toString(36)}`, Arn: adding.value }]);
    notify.success("Target added."); setAdding(null); reloadTargets(); reload();
  };
  const remove = async () => {
    await api.removeTargets(rule.Name, rule.EventBusName, sel.map((t) => t.Id));
    notify.success(`Removed ${sel.length} target${sel.length === 1 ? "" : "s"}.`); setSel([]); reloadTargets(); reload();
  };
  return (
    <CapabilityContainer id="eventbridge.rule.targets" title="Targets" counter={`(${targets.length})`} actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button disabled={!sel.length} onClick={remove}>Remove</Button>
        <Select placeholder="Select a target to add" selectedOption={adding} onChange={({ detail }) => setAdding(detail.selectedOption)} options={options.map((o) => ({ value: o.arn, label: o.label }))} ariaLabel="Add target" />
        <Button disabled={!adding} onClick={add}>Add target</Button>
      </SpaceBetween>
    }>
      <Table
        items={targets} selectionType="multi" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)} trackBy="Id"
        columnDefinitions={[
          { id: "name", header: "Target Name", cell: (t) => t.Id },
          { id: "type", header: "Type", cell: (t) => (t.Arn.includes(":sqs:") ? "SQS queue" : t.Arn.includes(":sns:") ? "SNS topic" : t.Arn.includes(":lambda:") ? "Lambda function" : t.Arn.includes(":states:") ? "Step Functions state machine" : t.Arn.includes(":kinesis:") ? "Kinesis stream" : "Other") },
          { id: "arn", header: "Arn", cell: (t) => t.Arn },
          { id: "input", header: "Input", cell: (t) => t.Input || "Matched event" },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No targets</b></Box>}
      />
    </CapabilityContainer>
  );
}

function TagsTab({ arn }) {
  const notify = useNotify();
  const { data: loaded, reload } = useAsync(() => api.listTagsForResource(arn), [arn]);
  const [tags, setTags] = useState(null);
  const shown = tags ?? (loaded || []).map((t) => ({ key: t.Key, value: t.Value }));
  const save = async () => {
    const before = (loaded || []).map((t) => ({ key: t.Key, value: t.Value }));
    const removed = before.filter((b) => !shown.some((s) => s.key === b.key));
    const added = shown.filter((s) => s.key && !before.some((b) => b.key === s.key && b.value === s.value));
    if (removed.length) await api.untagResource(arn, removed.map((t) => t.key));
    if (added.length) await api.tagResource(arn, added.map((t) => ({ Key: t.key, Value: t.value })));
    notify.success("Tags updated."); setTags(null); reload();
  };
  return (
    <SpaceBetween size="l">
      <TagEditor tags={shown} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={{
        keyHeader: "Key", valueHeader: "Value", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo",
        undoPrompt: "Removed upon saving", loading: "Loading tags", keyPlaceholder: "Key", valuePlaceholder: "Value",
        emptyTags: "No tags associated with this resource.", emptyKeyError: "You must specify a tag key",
        maxKeyCharLengthError: "128 character limit.", maxValueCharLengthError: "256 character limit.",
        duplicateKeyError: "Unique key required.", invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.", awsPrefixError: "Cannot start with aws:",
        tagLimit: (a) => `You can add up to ${a} more tags.`, tagLimitReached: () => "Tag limit reached.", tagLimitExceeded: () => "Tag limit exceeded.",
      }} />
      <Box float="left"><Button onClick={save}>Save changes</Button></Box>
    </SpaceBetween>
  );
}

export default function RuleDetail({ params, query }) {
  const name = params.name;
  const busName = query?.bus || "default";
  const rule = useAsync(() => api.describeRule(name, busName), [name, busName]);
  const [deleting, setDeleting] = useState(false);
  const notify = useNotify();
  if (rule.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (rule.error) return <ErrorAlert error={rule.error} />;
  const d = rule.data;

  const toggle = async () => {
    try { await (d.State === "ENABLED" ? api.disableRule(name, busName) : api.enableRule(name, busName)); notify.success(`${d.State === "ENABLED" ? "Disabled" : "Enabled"} rule.`); rule.reload(); }
    catch (e) { notify.error(e); }
  };

  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={rule.reload} iconName="refresh" ariaLabel="Refresh" />
        <Button onClick={toggle}>{d.State === "ENABLED" ? "Disable" : "Enable"}</Button>
        <Button href={`${href("eventbridge", "rules", name, "edit")}?bus=${encodeURIComponent(busName)}`} onFollow={follow}>Edit</Button>
        <Button onClick={() => setDeleting(true)}>Delete</Button>
      </SpaceBetween>
    }>{d.Name}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Rule details" columns={4} items={[
          ["Rule name", d.Name], ["Status", <Status key="s" ok={d.State === "ENABLED"}>{d.State}</Status>],
          ["Type", ruleType(d)], ["Description", d.Description || "-"],
          ["Event bus", d.EventBusName], ["Rule ARN", d.Arn],
        ]} />
        <Tabs tabs={[
          { id: "pattern", label: "Event pattern", content: <EventPatternTab rule={d} reload={rule.reload} /> },
          { id: "targets", label: "Targets", content: <TargetsTab rule={d} reload={rule.reload} /> },
          { id: "monitoring", label: "Monitoring", content: <NotSimulatedContainer title="Metrics" note="CloudWatch metrics for rule invocations aren't aggregated in Vyomi." /> },
          { id: "tags", label: "Tags", content: <TagsTab arn={d.Arn} /> },
        ]} />
      </SpaceBetween>
      {deleting && (
        <DeleteModal visible resourceType="rule" names={[name]} onDismiss={() => setDeleting(false)}
          onConfirm={async () => { await api.deleteRule(name, busName); notify.success(`Deleted rule ${name}.`); navigate("eventbridge", "rules"); }} />
      )}
    </ContentLayout>
  );
}
