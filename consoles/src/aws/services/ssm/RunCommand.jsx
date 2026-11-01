/* Run a command — real SendCommand. Vyomi has no SSM Agent fleet, so every instance ID
 * you name completes immediately as Success (same shape Run Command always reports). */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { follow, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function RunCommand() {
  const notify = useNotify();
  const docs = useAsync(() => api.listCommandDocuments(), []);
  const [doc, setDoc] = useState(null);
  const [instanceIds, setInstanceIds] = useState("");
  const [commands, setCommands] = useState("echo hello from Vyomi");
  const [comment, setComment] = useState("");
  const [timeout, setTimeoutS] = useState("600");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);
  const docOptions = (docs.data || []).map((d) => ({ value: d.Name, label: d.Name }));
  const ids = instanceIds.split(",").map((s) => s.trim()).filter(Boolean);

  const submit = async () => {
    setTouched(true);
    if (!doc || !ids.length) return;
    setBusy(true); setError(null);
    try {
      const command = await api.sendCommand({
        DocumentName: doc.value, InstanceIds: ids, TimeoutSeconds: Number(timeout) || 600,
        ...(comment ? { Comment: comment } : {}),
        Parameters: { commands: commands.split("\n").filter(Boolean) },
      });
      notify.success(`Command "${command.CommandId}" sent.`);
      navigate("ssm", "commands", command.CommandId);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Run a command</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button formAction="none" variant="link" href="#/ssm/commands" onFollow={follow}>Cancel</Button>
              <Button variant="primary" loading={busy}>Run</Button>
            </SpaceBetween>
          }
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Command document</Header>}>
              <FormField label="Document" errorText={touched && !doc ? "Choose a document." : null}>
                <Select selectedOption={doc} onChange={({ detail }) => setDoc(detail.selectedOption)} options={docOptions}
                  loadingText="Loading documents" statusType={docs.loading ? "loading" : "finished"} placeholder="Choose a document" />
              </FormField>
            </Container>
            <Container header={<Header variant="h2" description="One shell command per line, run as the commands parameter.">Command parameters</Header>}>
              <Textarea rows={6} value={commands} onChange={({ detail }) => setCommands(detail.value)} spellcheck={false} ariaLabel="Commands" />
            </Container>
            <Container header={<Header variant="h2">Targets</Header>}>
              <FormField label="Instance IDs" errorText={touched && !ids.length ? "Enter at least one instance ID." : null} constraintText="Comma-separated (i-xxxxxxxxxxxxxxxxx or mi-xxxxxxxxxxxxxxxxx).">
                <Input value={instanceIds} placeholder="i-0123456789abcdef0" onChange={({ detail }) => setInstanceIds(detail.value)} onBlur={() => setTouched(true)} ariaLabel="Instance IDs" />
              </FormField>
            </Container>
            <Container header={<Header variant="h2">Other parameters</Header>}>
              <SpaceBetween size="l">
                <FormField label="Comment - optional"><Input value={comment} onChange={({ detail }) => setComment(detail.value)} /></FormField>
                <FormField label="Timeout (seconds)"><Input type="number" value={timeout} onChange={({ detail }) => setTimeoutS(detail.value)} /></FormField>
              </SpaceBetween>
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
