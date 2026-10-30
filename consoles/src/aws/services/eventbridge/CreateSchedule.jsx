import { useEffect, useState } from "react";
import Box from "@cloudscape-design/components/box";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Toggle from "@cloudscape-design/components/toggle";
import Wizard from "@cloudscape-design/components/wizard";
import { ErrorAlert, KeyValue, NotSimulated } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { WIZARD_I18N } from "./common.jsx";
import * as api from "./api.js";

export default function CreateSchedule({ query }) {
  const editing = !!query?.name;
  const notify = useNotify();
  const { data: groups = [] } = useAsync(() => api.listScheduleGroups());
  const { data: targetOptions = [] } = useAsync(() => api.listAllTargets());
  const existing = useAsync(() => (editing ? api.getSchedule(query.name, query.group) : Promise.resolve(null)), [query?.name]);

  const [step, setStep] = useState(0);
  const [name, setName] = useState(query?.name || "");
  const [description, setDescription] = useState("");
  const [group, setGroup] = useState(query?.group || "default");
  const [occurrence, setOccurrence] = useState("recurring");
  const [kind, setKind] = useState("rate");
  const [at, setAt] = useState("");
  const [rate, setRate] = useState("5 minutes");
  const [cron, setCron] = useState("0 12 * * ? *");
  const [flexible, setFlexible] = useState(false);
  const [flexMinutes, setFlexMinutes] = useState("15");
  const [target, setTarget] = useState(null);
  const [input, setInput] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (existing.data) {
      const d = existing.data;
      setDescription(d.Description || "");
      setEnabled(d.State === "ENABLED");
      setTarget(d.Target ? { value: d.Target.Arn, label: d.Target.Arn.split(":").pop() } : null);
      setInput(d.Target?.Input || "");
      setFlexible((d.FlexibleTimeWindow?.Mode || "OFF") !== "OFF");
      setFlexMinutes(String(d.FlexibleTimeWindow?.MaximumWindowInMinutes || 15));
      const expr = d.ScheduleExpression || "";
      if (expr.startsWith("at(")) { setOccurrence("one-time"); setAt(expr.slice(3, -1)); }
      else if (expr.startsWith("rate(")) { setOccurrence("recurring"); setKind("rate"); setRate(expr.slice(5, -1)); }
      else if (expr.startsWith("cron(")) { setOccurrence("recurring"); setKind("cron"); setCron(expr.slice(5, -1)); }
    }
  }, [existing.data]);

  const scheduleExpr = occurrence === "one-time" ? `at(${at})` : kind === "rate" ? `rate(${rate})` : `cron(${cron})`;
  const nameErr = !name ? "Enter a schedule name." : null;

  const submit = async () => {
    if (!name || !target) { setStep(0); return; }
    setBusy(true); setError(null);
    try {
      const body = {
        GroupName: group, ScheduleExpression: scheduleExpr, State: enabled ? "ENABLED" : "DISABLED", Description: description,
        FlexibleTimeWindow: flexible ? { Mode: "FLEXIBLE", MaximumWindowInMinutes: Number(flexMinutes) || 15 } : { Mode: "OFF" },
        Target: { Arn: target.value, ...(input ? { Input: input } : {}) },
      };
      if (editing) await api.updateSchedule(name, body); else await api.createSchedule(name, body);
      notify.success(`${editing ? "Updated" : "Created"} schedule ${name}.`);
      navigate("eventbridge", "schedules");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">{editing ? `Edit schedule: ${name}` : "Create schedule"}</Header>}>
      {error && <ErrorAlert error={error} />}
      <Wizard
        i18nStrings={WIZARD_I18N}
        activeStepIndex={step}
        onNavigate={({ detail }) => setStep(detail.requestedStepIndex)}
        onCancel={() => navigate("eventbridge", "schedules")}
        onSubmit={submit}
        isLoadingNextStep={busy}
        steps={[
          {
            title: "Specify schedule detail",
            content: (
              <SpaceBetween size="l">
                <Container header={<Header variant="h2">Schedule name and description</Header>}>
                  <SpaceBetween size="l">
                    <FormField label="Schedule name" errorText={nameErr}><Input value={name} disabled={editing} onChange={({ detail }) => setName(detail.value)} ariaLabel="Schedule name" /></FormField>
                    <FormField label="Description - optional"><Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" /></FormField>
                    <FormField label="Schedule group">
                      <Select selectedOption={{ value: group, label: group }} disabled={editing} onChange={({ detail }) => setGroup(detail.selectedOption.value)}
                        options={groups.map((g) => ({ value: g.Name, label: g.Name }))} ariaLabel="Schedule group" />
                    </FormField>
                  </SpaceBetween>
                </Container>
                <Container header={<Header variant="h2">Schedule pattern</Header>}>
                  <SpaceBetween size="l">
                    <FormField label="Occurrence">
                      <RadioGroup value={occurrence} onChange={({ detail }) => setOccurrence(detail.value)}
                        items={[{ value: "one-time", label: "One-time schedule" }, { value: "recurring", label: "Recurring schedule" }]} />
                    </FormField>
                    {occurrence === "one-time" ? (
                      <FormField label="Date and time" description='UTC, e.g. "2026-12-01T09:00:00"'><Input value={at} onChange={({ detail }) => setAt(detail.value)} ariaLabel="Date and time" /></FormField>
                    ) : (
                      <>
                        <FormField label="Schedule type">
                          <RadioGroup value={kind} onChange={({ detail }) => setKind(detail.value)} items={[{ value: "rate", label: "Rate-based schedule" }, { value: "cron", label: "Cron-based schedule" }]} />
                        </FormField>
                        {kind === "rate"
                          ? <FormField label="Rate expression" description='e.g. "5 minutes", "1 hour", "1 day"'><Input value={rate} onChange={({ detail }) => setRate(detail.value)} ariaLabel="Rate expression" /></FormField>
                          : <FormField label="Cron expression" description="AWS cron: minutes hours day-of-month month day-of-week year"><Input value={cron} onChange={({ detail }) => setCron(detail.value)} ariaLabel="Cron expression" /></FormField>}
                      </>
                    )}
                    <FormField label="Flexible time window">
                      <SpaceBetween size="xs">
                        <Toggle checked={flexible} onChange={({ detail }) => setFlexible(detail.checked)}>Turn on flexible time window</Toggle>
                        {flexible && <Input type="number" value={flexMinutes} onChange={({ detail }) => setFlexMinutes(detail.value)} ariaLabel="Maximum window in minutes" />}
                      </SpaceBetween>
                    </FormField>
                    <Box variant="small" color="text-body-secondary">Resulting expression: <code>{scheduleExpr}</code>.</Box>
                  </SpaceBetween>
                </Container>
              </SpaceBetween>
            ),
          },
          {
            title: "Select target",
            content: (
              <Container header={<Header variant="h2">Target detail</Header>}>
                <SpaceBetween size="l">
                  <FormField label="Target API" description="SQS, SNS and Lambda are the targets Vyomi actually delivers to.">
                    <Select selectedOption={target} placeholder="Select a target" onChange={({ detail }) => setTarget(detail.selectedOption)} options={targetOptions.map((o) => ({ value: o.arn, label: o.label }))} ariaLabel="Target API" />
                  </FormField>
                  <FormField label="Target" description="Optional JSON input passed to the target when the schedule fires.">
                    <Input value={input} onChange={({ detail }) => setInput(detail.value)} placeholder='{"key": "value"}' ariaLabel="Target input" />
                  </FormField>
                </SpaceBetween>
              </Container>
            ),
          },
          {
            title: "Settings",
            content: (
              <SpaceBetween size="l">
                <Container header={<Header variant="h2">Schedule state</Header>}>
                  <FormField label="Enable schedule"><Toggle checked={enabled} onChange={({ detail }) => setEnabled(detail.checked)}>Enabled</Toggle></FormField>
                </Container>
                <Container header={<Header variant="h2">Permissions</Header>}>
                  <FormField label="Execution role">
                    <NotSimulated feature="A dedicated per-schedule IAM execution role" note="Vyomi delivers using the appliance's own permissions." />
                  </FormField>
                </Container>
              </SpaceBetween>
            ),
          },
          {
            title: "Review and create schedule",
            content: (
              <Container header={<Header variant="h2">Review</Header>}>
                <KeyValue columns={2} items={[
                  ["Schedule name", name], ["Group", group], ["Schedule", scheduleExpr],
                  ["Target", target?.label || "None"], ["Enabled", enabled ? "Yes" : "No"],
                ]} />
              </Container>
            ),
          },
        ]}
      />
    </ContentLayout>
  );
}
