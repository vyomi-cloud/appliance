/* Create maintenance window — real CreateMaintenanceWindow. */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Toggle from "@cloudscape-design/components/toggle";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateMaintenanceWindow() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [schedule, setSchedule] = useState("cron(0 2 ? * SUN *)");
  const [duration, setDuration] = useState("4");
  const [cutoff, setCutoff] = useState("1");
  const [allowUnassociated, setAllowUnassociated] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);

  const submit = async () => {
    setTouched(true);
    if (!name) return;
    setBusy(true); setError(null);
    try {
      const { WindowId } = await api.createMaintenanceWindow({
        Name: name, Schedule: schedule, Duration: Number(duration), Cutoff: Number(cutoff),
        AllowUnassociatedTargets: allowUnassociated, ...(description ? { Description: description } : {}),
      });
      notify.success(`Successfully created maintenance window "${name}"`);
      navigate("ssm", "maintenance-windows", WindowId);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create maintenance window</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button formAction="none" variant="link" href="#/ssm/maintenance-windows" onFollow={follow}>Cancel</Button>
              <Button variant="primary" loading={busy}>Create maintenance window</Button>
            </SpaceBetween>
          }
          errorText={error && <ErrorAlert error={error} />}
        >
          <Container header={<Header variant="h2">Provide window details</Header>}>
            <SpaceBetween size="l">
              <FormField label="Name" errorText={touched && !name ? "Enter a name." : null}>
                <Input value={name} onChange={({ detail }) => setName(detail.value)} onBlur={() => setTouched(true)} ariaLabel="Name" />
              </FormField>
              <FormField label="Description - optional"><Textarea value={description} onChange={({ detail }) => setDescription(detail.value)} /></FormField>
              <FormField label="Specify schedule" constraintText="A cron(), rate() or at() expression.">
                <Input value={schedule} onChange={({ detail }) => setSchedule(detail.value)} ariaLabel="Schedule" />
              </FormField>
              <FormField label="Duration (hours)"><Input type="number" value={duration} onChange={({ detail }) => setDuration(detail.value)} /></FormField>
              <FormField label="Stop initiating tasks (hours before the end of the window)"><Input type="number" value={cutoff} onChange={({ detail }) => setCutoff(detail.value)} /></FormField>
              <FormField label="Allow unassociated targets">
                <Toggle checked={allowUnassociated} onChange={({ detail }) => setAllowUnassociated(detail.checked)}>Run tasks even without a target registered with this window</Toggle>
              </FormField>
            </SpaceBetween>
          </Container>
        </Form>
      </form>
    </ContentLayout>
  );
}
