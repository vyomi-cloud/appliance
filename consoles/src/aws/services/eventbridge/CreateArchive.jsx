import { useEffect, useState } from "react";
import Box from "@cloudscape-design/components/box";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Textarea from "@cloudscape-design/components/textarea";
import Wizard from "@cloudscape-design/components/wizard";
import { ErrorAlert, NotSimulated } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { WIZARD_I18N } from "./common.jsx";
import * as api from "./api.js";

export default function CreateArchive({ params }) {
  const editing = !!params?.name;
  const notify = useNotify();
  const { data: buses = [] } = useAsync(() => api.listEventBuses());
  const existing = useAsync(() => (editing ? api.describeArchive(params.name) : Promise.resolve(null)), [params?.name]);

  const [step, setStep] = useState(0);
  const [name, setName] = useState(params?.name || "");
  const [description, setDescription] = useState("");
  const [source, setSource] = useState("default");
  const [retention, setRetention] = useState("0");
  const [pattern, setPattern] = useState("{\n  \"source\": [\"my.app\"]\n}");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (existing.data) {
      setDescription(existing.data.Description || "");
      setRetention(String(existing.data.RetentionDays || 0));
      setPattern(existing.data.EventPattern || "{}");
    }
  }, [existing.data]);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      let parsed = {};
      try { parsed = pattern.trim() ? JSON.parse(pattern) : {}; } catch { throw new Error("Event pattern must be valid JSON."); }
      const bus = buses.find((b) => b.Name === source);
      if (editing) {
        await api.updateArchive({ ArchiveName: name, Description: description, RetentionDays: Number(retention) || 0, EventPattern: JSON.stringify(parsed) });
        notify.success(`Updated archive ${name}.`);
      } else {
        await api.createArchive({ ArchiveName: name, Description: description, EventSourceArn: bus?.Arn, RetentionDays: Number(retention) || 0, EventPattern: JSON.stringify(parsed) });
        notify.success(`Creating the ${name} archive.`);
      }
      navigate("eventbridge", "archives");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">{editing ? `Edit archive: ${name}` : "Create archive"}</Header>}>
      {error && <ErrorAlert error={error} />}
      <Wizard
        i18nStrings={WIZARD_I18N}
        activeStepIndex={step}
        onNavigate={({ detail }) => setStep(detail.requestedStepIndex)}
        onCancel={() => navigate("eventbridge", "archives")}
        onSubmit={submit}
        isLoadingNextStep={busy}
        steps={[
          {
            title: "Define archive details",
            content: (
              <SpaceBetween size="l">
                <Container header={<Header variant="h2">Archive detail</Header>}>
                  <SpaceBetween size="l">
                    <FormField label="Name"><Input value={name} disabled={editing} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
                    <FormField label="Description - optional"><Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" /></FormField>
                    <FormField label="Source" description="The event bus whose events this archive captures.">
                      <Select disabled={editing} selectedOption={{ value: source, label: source }} onChange={({ detail }) => setSource(detail.selectedOption.value)}
                        options={buses.map((b) => ({ value: b.Name, label: b.Name }))} ariaLabel="Source" />
                    </FormField>
                    <FormField label="Retention period" description="Days to retain archived events. 0 = indefinite.">
                      <SpaceBetween direction="horizontal" size="xs">
                        <Input type="number" value={retention} onChange={({ detail }) => setRetention(detail.value)} ariaLabel="Retention period" />
                        <Box variant="span">Custom Retention Period (days)</Box>
                      </SpaceBetween>
                    </FormField>
                  </SpaceBetween>
                </Container>
                <Container header={<Header variant="h2">Encryption</Header>}>
                  <FormField label="AWS Key Management Service (KMS) key">
                    <NotSimulated feature="Archive encryption with a customer KMS key" note="Archives are stored unencrypted inside Vyomi's own store." />
                  </FormField>
                </Container>
              </SpaceBetween>
            ),
          },
          {
            title: "Filter events",
            content: (
              <Container header={<Header variant="h2">Event pattern</Header>} description="Only events matching this pattern are captured into the archive.">
                <FormField label="Event pattern" stretch>
                  <Textarea value={pattern} onChange={({ detail }) => setPattern(detail.value)} rows={10} ariaLabel="Event pattern" />
                </FormField>
              </Container>
            ),
          },
        ]}
      />
    </ContentLayout>
  );
}
