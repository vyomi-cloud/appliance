/* Create policy — defaults to the real JSON editor path (validated client-side);
 * "Visual" editor isn't modeled (no per-service action/resource picker is computed). */
import { useState } from "react";
import Wizard from "@cloudscape-design/components/wizard";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

const DEFAULT_DOC = JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Action: "s3:ListAllMyBuckets", Resource: "*" }] }, null, 2);
const SERVICES = ["S3", "DynamoDB", "KMS", "IAM", "EC2", "Lambda"];

function PermissionsStep({ s, set, jsonErr }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Policy editor</Header>}>
        <SpaceBetween size="m">
          <RadioGroup value={s.editor} onChange={({ detail }) => set({ editor: detail.value })} items={[{ value: "Visual", label: "Visual" }, { value: "JSON", label: "JSON" }]} />
          {s.editor === "Visual" ? (
            <NotSimulatedContainer title="Visual policy editor"
              note="Vyomi doesn't model the service/actions/resources/conditions picker — switch to the JSON editor above to write the policy document directly." />
          ) : (
            <>
              <FormField label="Service" description="Visual editor: Select a service, then actions, resources and conditions">
                <Select selectedOption={s.service ? { value: s.service, label: s.service } : null} onChange={({ detail }) => set({ service: detail.selectedOption.value })}
                  options={SERVICES.map((v) => ({ value: v, label: v }))} placeholder="Choose a service" />
              </FormField>
              <FormField label="Policy document" errorText={jsonErr}>
                <Textarea rows={16} value={s.doc} onChange={({ detail }) => set({ doc: detail.value })} spellcheck={false} />
              </FormField>
              <Button onClick={() => {}}>Add more permissions</Button>
            </>
          )}
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );
}

function ReviewStep({ s, set }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Policy details</Header>}>
        <SpaceBetween size="m">
          <FormField label="Policy name" constraintText="Maximum 128 characters. Use alphanumeric and '+=,.@-_' characters.">
            <Input value={s.name} onChange={({ detail }) => set({ name: detail.value })} ariaLabel="Policy name" />
          </FormField>
          <FormField label="Description - optional" constraintText="Maximum 1,000 characters.">
            <Textarea value={s.description} onChange={({ detail }) => set({ description: detail.value })} ariaLabel="Description - optional" />
          </FormField>
        </SpaceBetween>
      </Container>
      <Container header={<Header variant="h2">Permissions defined in this policy</Header>}>
        <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{s.doc}</pre></Box>
      </Container>
      <Container header={<Header variant="h2">Add tags - optional</Header>}>
        <FormField label="Tags"><TagEditor tags={s.tags} onChange={({ detail }) => set({ tags: detail.tags })} /></FormField>
      </Container>
    </SpaceBetween>
  );
}

export default function CreatePolicy() {
  const notify = useNotify();
  const [idx, setIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [jsonErr, setJsonErr] = useState(null);
  const [s, setS] = useState({ editor: "JSON", service: "", doc: DEFAULT_DOC, name: "", description: "", tags: [] });
  const set = (patch) => setS((prev) => ({ ...prev, ...patch }));

  const finish = async () => {
    try { JSON.parse(s.doc); } catch (e) { setJsonErr(`Policy document is not valid JSON: ${e.message}`); setIdx(0); return; }
    setJsonErr(null); setBusy(true); setError(null);
    try {
      const tags = s.tags.filter((t) => !t.markedForRemoval && t.key);
      await api.createPolicy({ PolicyName: s.name, PolicyDocument: s.doc, Description: s.description, ...api.tagsParams(tags) });
      notify.success(`Policy "${s.name}" created.`);
      navigate("iam", "policies", s.name);
    } catch (e) { setError(e); setIdx(1); } finally { setBusy(false); }
  };

  const steps = [
    { title: "Specify permissions", content: <PermissionsStep s={s} set={set} jsonErr={jsonErr} /> },
    { title: "Review and create", content: <>
      {error && <Box padding={{ bottom: "s" }}><ErrorAlert error={error} header="Couldn't create policy" /></Box>}
      <ReviewStep s={s} set={set} />
    </> },
  ];

  return (
    <Box padding={{ top: "l" }}>
      <Wizard
        activeStepIndex={idx}
        onNavigate={({ detail }) => setIdx(detail.requestedStepIndex)}
        onCancel={() => navigate("iam", "policies")}
        onSubmit={finish}
        isLoadingNextStep={busy}
        submitButtonText="Create policy"
        i18nStrings={{ stepNumberLabel: (n) => `Step ${n}`, collapsedStepsLabel: (n, total) => `Step ${n} of ${total}`, cancelButton: "Cancel", previousButton: "Previous", nextButton: "Next", optional: "optional" }}
        steps={steps}
      />
    </Box>
  );
}
