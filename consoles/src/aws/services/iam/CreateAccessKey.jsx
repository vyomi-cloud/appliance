/* Create access key — use-case radio + CreateAccessKey + show-once secret + .csv download. */
import { useState } from "react";
import Wizard from "@cloudscape-design/components/wizard";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Checkbox from "@cloudscape-design/components/checkbox";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const USE_CASES = ["Command Line Interface (CLI)", "Local code", "Application running on an AWS compute service", "Third-party service", "Application running outside AWS", "Other"];

export default function CreateAccessKey({ params }) {
  const userName = params.name;
  const notify = useNotify();
  const [idx, setIdx] = useState(0);
  const [useCase, setUseCase] = useState(USE_CASES[0]);
  const [understood, setUnderstood] = useState(false);
  const [descTag, setDescTag] = useState("");
  const [created, setCreated] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const createKey = async () => {
    setBusy(true); setError(null);
    try { const ak = await api.createAccessKey(userName); setCreated(ak); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };

  const download = () => {
    const csv = `Access key ID,Secret access key\n${created.AccessKeyId},${created.SecretAccessKey}\n`;
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${userName}_accessKeys.csv`; a.click();
  };

  const steps = [
    { title: "Access key best practices & alternatives", content: (
      <Container header={<Header variant="h2">Use case</Header>}>
        <SpaceBetween size="m">
          <RadioGroup value={useCase} onChange={({ detail }) => setUseCase(detail.value)} items={USE_CASES.map((v) => ({ value: v, label: v }))} />
          <Checkbox checked={understood} onChange={({ detail }) => setUnderstood(detail.checked)}>I understand the above recommendation and want to proceed to create an access key.</Checkbox>
        </SpaceBetween>
      </Container>
    ) },
    { title: "Set description tag - optional", content: (
      <Container header={<Header variant="h2">Description tag value</Header>}>
        <FormField label="Description tag value" constraintText="Maximum 256 characters.">
          <Input value={descTag} onChange={({ detail }) => setDescTag(detail.value)} ariaLabel="Description tag value" />
        </FormField>
      </Container>
    ) },
    { title: "Retrieve access keys", content: (
      <Container header={<Header variant="h2">Access key</Header>}>
        {error && <Box padding={{ bottom: "s" }}><ErrorAlert error={error} header="Couldn't create access key" /></Box>}
        {created ? (
          <SpaceBetween size="m">
            <FormField label="Access key"><Input value={created.AccessKeyId} readOnly ariaLabel="Access key" /></FormField>
            <FormField label="Secret access key"><Input value={created.SecretAccessKey} readOnly ariaLabel="Secret access key" /></FormField>
            <Button onClick={download}>Download .csv file</Button>
          </SpaceBetween>
        ) : <Box>Creating access key…</Box>}
      </Container>
    ) },
  ];

  return (
    <Box padding={{ top: "l" }}>
      <Wizard
        activeStepIndex={idx}
        onNavigate={({ detail }) => {
          if (detail.requestedStepIndex === 2 && idx < 2) createKey();
          setIdx(detail.requestedStepIndex);
        }}
        onCancel={() => navigate("iam", "users", userName)}
        onSubmit={() => navigate("iam", "users", userName)}
        isLoadingNextStep={busy}
        submitButtonText="Done"
        i18nStrings={{ stepNumberLabel: (n) => `Step ${n}`, collapsedStepsLabel: (n, total) => `Step ${n} of ${total}`, cancelButton: "Cancel", previousButton: "Previous", nextButton: "Next", optional: "optional" }}
        steps={steps}
      />
    </Box>
  );
}
