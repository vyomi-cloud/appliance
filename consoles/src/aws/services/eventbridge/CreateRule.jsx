import { useEffect, useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tabs from "@cloudscape-design/components/tabs";
import TagEditor from "@cloudscape-design/components/tag-editor";
import Textarea from "@cloudscape-design/components/textarea";
import Toggle from "@cloudscape-design/components/toggle";
import { ErrorAlert, NotSimulated } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import * as api from "./api.js";

const SAMPLE_PATTERN = '{\n  "source": ["my.app"],\n  "detail-type": ["x"]\n}';
const SAMPLE_EVENT = '{\n  "source": "my.app",\n  "detail-type": "x",\n  "detail": {}\n}';

/** A faithful JS port of core/eventbridge_core.py's _match_pattern — so "Test pattern"
 * is a real, local, deterministic check, not a fake button. */
function matchValue(cond, value) {
  if (cond && typeof cond === "object" && !Array.isArray(cond)) {
    if ("prefix" in cond) return typeof value === "string" && value.startsWith(cond.prefix);
    if ("anything-but" in cond) { const ab = Array.isArray(cond["anything-but"]) ? cond["anything-but"] : [cond["anything-but"]]; return !ab.includes(value); }
    if ("exists" in cond) return (value !== undefined && value !== null) === !!cond.exists;
    return false;
  }
  return cond === value;
}
function matchPattern(pattern, event) {
  for (const [key, expected] of Object.entries(pattern || {})) {
    const actual = event?.[key];
    if (expected && typeof expected === "object" && !Array.isArray(expected) && !["prefix", "anything-but", "exists"].some((k) => k in expected)) {
      if (!actual || typeof actual !== "object" || !matchPattern(expected, actual)) return false;
      continue;
    }
    const options = Array.isArray(expected) ? expected : [expected];
    if (!options.some((o) => matchValue(o, actual))) return false;
  }
  return true;
}

function TargetRow({ idx, target, onChange, onRemove, options }) {
  return (
    <Container header={<Header variant="h3" actions={<Button onClick={onRemove}>Remove</Button>}>{`Target ${idx + 1}`}</Header>}>
      <SpaceBetween size="l">
        <FormField label="Target types" description="SQS queue, SNS topic or Lambda function — the targets Vyomi actually delivers to.">
          <Select selectedOption={target.arn ? { value: target.arn, label: target.label } : null}
            onChange={({ detail }) => onChange({ ...target, arn: detail.selectedOption.value, label: detail.selectedOption.label })}
            options={options.map((o) => ({ value: o.arn, label: o.label }))} placeholder="Select a target" ariaLabel="Select a target" />
        </FormField>
        <FormField label="Execution role" description="Vyomi delivers directly; no IAM role is assumed for delivery.">
          <NotSimulated feature="A dedicated per-target execution role" note="Vyomi delivers using the appliance's own permissions." />
        </FormField>
        <FormField label="Input" description="Optional JSON passed to the target instead of the matched event.">
          <Textarea value={target.input || ""} onChange={({ detail }) => onChange({ ...target, input: detail.value })} rows={3} ariaLabel="Target input" />
        </FormField>
      </SpaceBetween>
    </Container>
  );
}

export default function CreateRule({ params, query }) {
  const editing = !!params?.name;
  const notify = useNotify();
  const { data: buses = [] } = useAsync(() => api.listEventBuses());
  const { data: targetOptions = [] } = useAsync(() => api.listAllTargets());
  const existing = useAsync(() => (editing ? api.describeRule(params.name, query?.bus) : Promise.resolve(null)), [params?.name]);
  const existingTargets = useAsync(() => (editing ? api.listTargetsByRule(params.name, query?.bus) : Promise.resolve([])), [params?.name]);

  const [name, setName] = useState(editing ? params.name : "");
  const [description, setDescription] = useState("");
  const [bus, setBus] = useState(query?.bus || "default");
  const [active, setActive] = useState(true);
  const [pattern, setPattern] = useState(SAMPLE_PATTERN);
  const [sampleEvent, setSampleEvent] = useState(SAMPLE_EVENT);
  const [testResult, setTestResult] = useState(null);
  const [targets, setTargets] = useState([]);
  const [tags, setTags] = useState([]);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (existing.data) {
      setDescription(existing.data.Description || "");
      setBus(existing.data.EventBusName || "default");
      setActive(existing.data.State === "ENABLED");
      setPattern(existing.data.EventPattern || SAMPLE_PATTERN);
    }
  }, [existing.data]);
  useEffect(() => {
    if (existingTargets.data?.length) setTargets(existingTargets.data.map((t) => ({ id: t.Id, arn: t.Arn, label: t.Arn, input: t.Input || "" })));
  }, [existingTargets.data]);

  const testPattern = () => {
    try {
      const ok = matchPattern(JSON.parse(pattern || "{}"), JSON.parse(sampleEvent || "{}"));
      setTestResult(ok ? "match" : "nomatch");
    } catch { setTestResult("invalid"); }
  };

  const nameErr = touched && !/^[.\-_A-Za-z0-9]{1,64}$/.test(name) ? "Enter a valid rule name (letters, numbers, ., -, _, up to 64 characters)." : null;

  const submit = async () => {
    setTouched(true);
    if (!/^[.\-_A-Za-z0-9]{1,64}$/.test(name)) return;
    let parsedPattern;
    try { parsedPattern = pattern.trim() ? JSON.parse(pattern) : {}; } catch { setError(new Error("Event pattern must be valid JSON.")); return; }
    setBusy(true); setError(null);
    try {
      await api.putRule({
        Name: name, EventBusName: bus, Description: description, State: active ? "ENABLED" : "DISABLED",
        EventPattern: JSON.stringify(parsedPattern), Tags: tags.filter((t) => t.key).map((t) => ({ Key: t.key, Value: t.value })),
      });
      if (editing) {
        const removedIds = (existingTargets.data || []).map((t) => t.Id).filter((id) => !targets.some((t) => t.id === id));
        if (removedIds.length) await api.removeTargets(name, bus, removedIds);
      }
      if (targets.length) {
        await api.putTargets(name, bus, targets.map((t, i) => ({ Id: t.id || `t${i + 1}`, Arn: t.arn, ...(t.input ? { Input: t.input } : {}) })));
      }
      notify.success(editing ? `Updated rule ${name}.` : `Rule ${name} was created.`);
      navigate("eventbridge", bus === "default" ? "rules" : "event-buses", ...(bus === "default" ? [] : [bus]));
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create rule</Header>}>
      {error && <ErrorAlert error={error} />}
      <Tabs tabs={[
        {
          id: "build", label: "Build", content: (
            <SpaceBetween size="l">
              <Box variant="small" color="text-body-secondary" data-vyomi-not-simulated="Builder mode">
                The drag-and-drop Builder mode (Palette, Canvas, Triggering Events) isn't simulated in Vyomi — use the Event pattern (filter) editor below.
              </Box>
              <Container header={<Header variant="h2">Event pattern (filter)</Header>}>
                <SpaceBetween size="l">
                  <FormField label="Event pattern" stretch description="Events on this bus matching this pattern trigger the rule's targets.">
                    <Textarea value={pattern} onChange={({ detail }) => setPattern(detail.value)} rows={8} ariaLabel="Event pattern" />
                  </FormField>
                </SpaceBetween>
              </Container>
              <Container header={<Header variant="h2">Test event pattern - optional</Header>}>
                <SpaceBetween size="l">
                  <FormField label="Sample event" stretch description="Paste a sample triggering event and test it against the pattern above.">
                    <Textarea value={sampleEvent} onChange={({ detail }) => setSampleEvent(detail.value)} rows={6} ariaLabel="Sample event" />
                  </FormField>
                  <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                    <Button onClick={testPattern}>Test pattern</Button>
                    {testResult === "match" && <Box color="text-status-success">Pattern matches the sample event.</Box>}
                    {testResult === "nomatch" && <Box color="text-status-error">Pattern does not match the sample event.</Box>}
                    {testResult === "invalid" && <Box color="text-status-error">Pattern or sample event is not valid JSON.</Box>}
                  </SpaceBetween>
                </SpaceBetween>
              </Container>
              <CapabilityContainer id="eventbridge.rule.targets" title="Targets" actions={<Button onClick={() => setTargets([...targets, { arn: "", label: "", input: "" }])}>Add target</Button>}>
                <SpaceBetween size="l">
                  {targets.map((t, i) => (
                    <TargetRow key={i} idx={i} target={t} options={targetOptions}
                      onChange={(nt) => setTargets(targets.map((x, j) => (j === i ? nt : x)))}
                      onRemove={() => setTargets(targets.filter((_, j) => j !== i))} />
                  ))}
                  {!targets.length && <Box color="text-body-secondary">No targets added. The rule will match events but deliver nowhere.</Box>}
                </SpaceBetween>
              </CapabilityContainer>
            </SpaceBetween>
          ),
        },
        {
          id: "configure", label: "Configure", content: (
            <SpaceBetween size="l">
              <Container header={<Header variant="h2">Name and description</Header>}>
                <SpaceBetween size="l">
                  <FormField label="Rule name" errorText={nameErr}><Input value={name} disabled={editing} onChange={({ detail }) => setName(detail.value)} ariaLabel="Rule name" /></FormField>
                  <FormField label="Description - optional"><Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" /></FormField>
                  <FormField label="Rule type"><RadioGroup value="pattern" items={[{ value: "pattern", label: "Rule with an event pattern" }, { value: "schedule", label: "Schedule (use Create scheduled rule instead)", disabled: true }]} /></FormField>
                </SpaceBetween>
              </Container>
              <Container header={<Header variant="h2">Event bus</Header>}>
                <FormField label="Event bus name">
                  <Select selectedOption={{ value: bus, label: bus }} disabled={editing}
                    onChange={({ detail }) => setBus(detail.selectedOption.value)}
                    options={buses.map((b) => ({ value: b.Name, label: b.Name }))} ariaLabel="Event bus name" />
                </FormField>
              </Container>
              <Container header={<Header variant="h2">Activation</Header>}>
                <FormField label="Active"><Toggle checked={active} onChange={({ detail }) => setActive(detail.checked)}>Enable the rule on the selected event bus</Toggle></FormField>
              </Container>
              <Container header={<Header variant="h2">Tags - optional</Header>}>
                <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={{
                  keyHeader: "Key", valueHeader: "Value", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo",
                  undoPrompt: "Removed upon saving", loading: "Loading tags", keyPlaceholder: "Key", valuePlaceholder: "Value",
                  emptyTags: "No tags associated with this resource.", emptyKeyError: "You must specify a tag key",
                  maxKeyCharLengthError: "128 character limit.", maxValueCharLengthError: "256 character limit.",
                  duplicateKeyError: "Unique key required.", invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.", awsPrefixError: "Cannot start with aws:",
                  tagLimit: (a) => `You can add up to ${a} more tags.`, tagLimitReached: () => "Tag limit reached.", tagLimitExceeded: () => "Tag limit exceeded.",
                }} />
              </Container>
              <Box float="right">
                <SpaceBetween direction="horizontal" size="xs">
                  <Button variant="link" onClick={() => navigate("eventbridge", "rules")}>Cancel</Button>
                  <Button variant="primary" loading={busy} onClick={submit}>{editing ? "Update rule" : "Create rule"}</Button>
                </SpaceBetween>
              </Box>
            </SpaceBetween>
          ),
        },
      ]} />
    </ContentLayout>
  );
}
