import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
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
import TagEditor from "@cloudscape-design/components/tag-editor";
import Toggle from "@cloudscape-design/components/toggle";
import Wizard from "@cloudscape-design/components/wizard";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { WIZARD_I18N } from "./common.jsx";
import * as api from "./api.js";

export default function CreateScheduledRule() {
  const notify = useNotify();
  const { data: targetOptions = [] } = useAsync(() => api.listAllTargets());
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [active, setActive] = useState(true);
  const [kind, setKind] = useState("rate");
  const [rate, setRate] = useState("5 minutes");
  const [cron, setCron] = useState("0 12 * * ? *");
  const [target, setTarget] = useState(null);
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const scheduleExpr = kind === "rate" ? `rate(${rate})` : `cron(${cron})`;
  const nameErr = !name ? "Enter a name." : null;

  const submit = async () => {
    if (!name) { setStep(0); return; }
    setBusy(true); setError(null);
    try {
      await api.putRule({ Name: name, EventBusName: "default", Description: description, State: active ? "ENABLED" : "DISABLED",
        ScheduleExpression: scheduleExpr, Tags: tags.filter((t) => t.key).map((t) => ({ Key: t.key, Value: t.value })) });
      if (target) await api.putTargets(name, "default", [{ Id: "t1", Arn: target.value }]);
      notify.success(`Scheduled rule ${name} was created.`);
      navigate("eventbridge", "scheduled-rules");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create rule</Header>}>
      {error && <ErrorAlert error={error} />}
      <Wizard
        i18nStrings={WIZARD_I18N}
        activeStepIndex={step}
        onNavigate={({ detail }) => setStep(detail.requestedStepIndex)}
        onCancel={() => navigate("eventbridge", "scheduled-rules")}
        onSubmit={submit}
        isLoadingNextStep={busy}
        steps={[
          {
            title: "Define rule detail",
            content: (
              <SpaceBetween size="l">
                <Container header={<Header variant="h2">Scheduled rule detail</Header>}>
                  <SpaceBetween size="l">
                    <FormField label="Name" errorText={nameErr}><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
                    <FormField label="Description - optional"><Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" /></FormField>
                    <FormField label="Event bus"><Select selectedOption={{ value: "default", label: "default" }} disabled options={[{ value: "default", label: "default" }]} ariaLabel="Event bus" /></FormField>
                    <FormField label="Enable the rule on the selected event bus"><Toggle checked={active} onChange={({ detail }) => setActive(detail.checked)}>Enabled</Toggle></FormField>
                  </SpaceBetween>
                </Container>
                <Alert header="EventBridge Scheduler">Scheduled rules are the legacy way to run something on a schedule. EventBridge Scheduler supports one-time schedules, flexible time windows and per-schedule targets.</Alert>
              </SpaceBetween>
            ),
          },
          {
            title: "Define schedule",
            content: (
              <Container header={<Header variant="h2">Schedule pattern</Header>}>
                <SpaceBetween size="l">
                  <FormField label="Schedule pattern">
                    <RadioGroup value={kind} onChange={({ detail }) => setKind(detail.value)} items={[{ value: "rate", label: "Rate-based schedule" }, { value: "cron", label: "Cron-based schedule" }]} />
                  </FormField>
                  {kind === "rate"
                    ? <FormField label="Rate expression" description='e.g. "5 minutes", "1 hour", "1 day"'><Input value={rate} onChange={({ detail }) => setRate(detail.value)} ariaLabel="Rate expression" /></FormField>
                    : <FormField label="Cron expression" description="AWS cron: minutes hours day-of-month month day-of-week year"><Input value={cron} onChange={({ detail }) => setCron(detail.value)} ariaLabel="Cron expression" /></FormField>}
                  <Box variant="small" color="text-body-secondary">Resulting expression: <code>{scheduleExpr}</code>. Scheduled rules don't fire automatically in Vyomi — use EventBridge Scheduler for real firing.</Box>
                </SpaceBetween>
              </Container>
            ),
          },
          {
            title: "Select target(s)",
            content: (
              <Container header={<Header variant="h2">Target 1</Header>}>
                <FormField label="Select a target">
                  <Select placeholder="Select a target" selectedOption={target} onChange={({ detail }) => setTarget(detail.selectedOption)} options={targetOptions.map((o) => ({ value: o.arn, label: o.label }))} ariaLabel="Select a target" />
                </FormField>
              </Container>
            ),
          },
          {
            title: "Configure tags",
            content: (
              <Container header={<Header variant="h2">Tags</Header>}>
                <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={{
                  keyHeader: "Key", valueHeader: "Value", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo",
                  undoPrompt: "Removed upon saving", loading: "Loading tags", keyPlaceholder: "Key", valuePlaceholder: "Value",
                  emptyTags: "No tags associated with this resource.", emptyKeyError: "You must specify a tag key",
                  maxKeyCharLengthError: "128 character limit.", maxValueCharLengthError: "256 character limit.",
                  duplicateKeyError: "Unique key required.", invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.", awsPrefixError: "Cannot start with aws:",
                  tagLimit: (a) => `You can add up to ${a} more tags.`, tagLimitReached: () => "Tag limit reached.", tagLimitExceeded: () => "Tag limit exceeded.",
                }} />
              </Container>
            ),
          },
          {
            title: "Review and create",
            content: (
              <Container header={<Header variant="h2">Review</Header>}>
                <KeyValue columns={2} items={[["Name", name], ["Description", description || "-"], ["Schedule", scheduleExpr], ["Target", target?.label || "None"], ["Enabled", active ? "Yes" : "No"]]} />
              </Container>
            ),
          },
        ]}
      />
    </ContentLayout>
  );
}
