import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import Checkbox from "@cloudscape-design/components/checkbox";
import Toggle from "@cloudscape-design/components/toggle";
import TagEditor from "@cloudscape-design/components/tag-editor";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import Alert from "@cloudscape-design/components/alert";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const LOG_LEVELS = [{ value: "OFF", label: "OFF" }, { value: "ERROR", label: "ERROR" }, { value: "ALL", label: "ALL" }];

export default function CreateStateMachine() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [type, setType] = useState("STANDARD");
  const [definition, setDefinition] = useState(api.DEFAULT_DEFINITION);
  const [roleArn, setRoleArn] = useState(api.DEFAULT_ROLE_ARN);
  const [logLevel, setLogLevel] = useState("OFF");
  const [includeExecData, setIncludeExecData] = useState(false);
  const [tracing, setTracing] = useState(false);
  const [tags, setTags] = useState([]);
  const [validation, setValidation] = useState(null);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched && !name.trim() ? "State machine name is required." : null;
  const defErr = touched && !definition.trim() ? "Definition is required." : null;

  const validate = async () => {
    try { setValidation(await api.validateDefinition(definition)); }
    catch (e) { notify.error(e); }
  };

  const submit = async () => {
    setTouched(true);
    if (!name.trim() || !definition.trim()) return;
    setBusy(true); setError(null);
    try {
      await api.createStateMachine({
        name, type, definition, roleArn,
        loggingConfiguration: { level: logLevel, includeExecutionData: includeExecData, destinations: [] },
        tracingConfiguration: { enabled: tracing },
        tags: tags.filter((t) => !t.markedForRemoval && t.key).map((t) => ({ key: t.key, value: t.value })),
      });
      notify.success(`Creating "${name}" state machine.`);
      navigate("states", "state-machines", name);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create state machine</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form errorText={error && <ErrorAlert error={error} />} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href="#/states/state-machines" onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Create state machine</Button>
          </SpaceBetween>
        }>
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Define state machine</Header>}>
              <SpaceBetween size="l">
                <FormField label="Name" errorText={nameErr} constraintText="1 to 80 characters.">
                  <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="Enter the state machine name" ariaLabel="Name" />
                </FormField>
                <FormField label="Type">
                  <RadioGroup value={type} onChange={({ detail }) => setType(detail.value)} items={[
                    { value: "STANDARD", label: "Standard" },
                    { value: "EXPRESS", label: "Express" },
                  ]} />
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2" description="Amazon States Language (ASL), as JSON." actions={<Button formAction="none" onClick={validate}>Validate state machine definition</Button>}>Definition</Header>}>
              <SpaceBetween size="m">
                <FormField label="Definition" errorText={defErr}>
                  <Textarea rows={16} spellcheck={false} value={definition} onChange={({ detail }) => { setDefinition(detail.value); setValidation(null); }} ariaLabel="Definition" />
                </FormField>
                {validation && (
                  <Alert type={validation.result === "OK" ? "success" : "error"} header={validation.result === "OK" ? "Definition is valid" : "Definition has errors"}>
                    {validation.result === "OK" ? "No problems found." : (
                      <ul style={{ margin: 0, paddingLeft: 18 }}>{validation.diagnostics.map((d, i) => <li key={i}>{d.message} ({d.location})</li>)}</ul>
                    )}
                  </Alert>
                )}
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Permissions</Header>}>
              <FormField label="Execution role" description="IAM role ARN the state machine assumes. Vyomi accepts any arn:aws:iam:: role; it is not validated against IAM.">
                <Input value={roleArn} onChange={({ detail }) => setRoleArn(detail.value)} ariaLabel="Execution role" />
              </FormField>
            </Container>

            <CapabilityContainer id="aws.states.state-machine.logging" title="Logging">
              <SpaceBetween size="l">
                <FormField label="Log level">
                  <Select selectedOption={LOG_LEVELS.find((l) => l.value === logLevel)} onChange={({ detail }) => setLogLevel(detail.selectedOption.value)} options={LOG_LEVELS} ariaLabel="Log level" />
                </FormField>
                <Checkbox checked={includeExecData} onChange={({ detail }) => setIncludeExecData(detail.checked)}>Include execution data in logs</Checkbox>
              </SpaceBetween>
            </CapabilityContainer>

            <CapabilityContainer id="aws.states.state-machine.tracing" title="X-Ray tracing">
              <Toggle checked={tracing} onChange={({ detail }) => setTracing(detail.checked)}>Active tracing</Toggle>
            </CapabilityContainer>

            <Container header={<Header variant="h2" description="Tags are pairs of keys and optional values that you can assign to AWS resources.">Tags</Header>}>
              <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={{
                keyHeader: "Key", valueHeader: "Value - optional", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo",
                undoPrompt: "This tag will be removed upon saving changes", loading: "Loading tags", keyPlaceholder: "Enter key", valuePlaceholder: "Enter value",
                emptyTags: "No tags are associated with the resource.", tooManyKeysSuggestion: "You have more keys than can be displayed",
                tooManyValuesSuggestion: "You have more values than can be displayed", keysSuggestionLoading: "Loading tag keys",
                keysSuggestionError: "Tag keys could not be retrieved", valuesSuggestionLoading: "Loading tag values", valuesSuggestionError: "Tag values could not be retrieved",
                emptyKeyError: "You must specify a tag key", maxKeyCharLengthError: "The maximum number of characters you can use in a tag key is 128.",
                maxValueCharLengthError: "The maximum number of characters you can use in a tag value is 256.", duplicateKeyError: "You must specify a unique tag key.",
                invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.", awsPrefixError: "Cannot start with aws:",
                tagLimit: (a) => `You can add up to ${a} more tags.`, tagLimitReached: () => "You have reached the limit of 50 tags.", tagLimitExceeded: () => "You have exceeded the limit of 50 tags.",
              }} />
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
