/* Create stack — 4-step wizard matching the native console. Steps 1-3 are real: the
 * template (S3 URL fetched through Vyomi's own S3 store, or an uploaded file read
 * client-side), stack name + per-template parameters (resolved via ValidateTemplate),
 * tags, capabilities and termination protection all reach CreateStack. "Sync from Git"
 * and "Build with template studio" are the declared gaps (core/capabilities/aws/
 * cloudformation.json: aws.cloudformation.stack.template) — stack policy / rollback
 * configuration / notification options are accepted and stored but not enforced,
 * the same "config_only" pattern as every other service's policy-document fields. */
import { useState } from "react";
import Wizard from "@cloudscape-design/components/wizard";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Checkbox from "@cloudscape-design/components/checkbox";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useNotify } from "../../../common/notify.jsx";
import { navigate, href, follow } from "../../../common/router.js";
import { ErrorAlert, NotSimulated } from "../../kit/common.jsx";
import * as api from "./api.js";

function CreateStackStep({ s, set, error }) {
  const onFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => set({ uploadedTemplate: String(reader.result || ""), uploadedName: f.name });
    reader.readAsText(f);
  };
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Prerequisite - Prepare template</Header>}>
        <FormField label="Prepare template">
          <RadioGroup value={s.prepareMode} onChange={({ detail }) => set({ prepareMode: detail.value })} items={[
            { value: "existing", label: "Choose an existing template" },
            { value: "studio", label: "Build with template studio" },
          ]} />
        </FormField>
        {s.prepareMode === "studio" && <Box padding={{ top: "s" }}><NotSimulated feature="Launching into Template studio from the wizard" note='Open Template studio directly from the nav, build your template, then come back here and choose "Upload a template file" to paste it in.' /></Box>}
      </Container>
      <Container header={<Header variant="h2" actions={<Button href={href("cloudformation", "template-studio")} onFollow={follow}>Open in template studio</Button>}>Specify template</Header>}>
        <SpaceBetween size="l">
          <FormField label="Template source">
            <RadioGroup value={s.templateSource} onChange={({ detail }) => set({ templateSource: detail.value })} items={[
              { value: "s3url", label: "Amazon S3 URL" },
              { value: "upload", label: "Upload a template file" },
              { value: "git", label: "Sync from Git" },
            ]} />
          </FormField>
          {s.templateSource === "s3url" && (
            <FormField label="Amazon S3 URL" constraintText="Enter template URL.">
              <Input value={s.s3Url} onChange={({ detail }) => set({ s3Url: detail.value })} placeholder="https://s3.amazonaws.com/my-bucket/template.json" ariaLabel="Amazon S3 URL" />
            </FormField>
          )}
          {s.templateSource === "upload" && (
            <FormField label="Upload a template file" description="JSON or YAML formatted file">
              <input type="file" accept=".json,.yaml,.yml,.template" onChange={onFile} aria-label="Upload a template file" />
              {s.uploadedName && <Box variant="small">{s.uploadedName} ({s.uploadedTemplate.length} bytes)</Box>}
            </FormField>
          )}
          {s.templateSource === "git" && <NotSimulated feature="Sync from Git" note="Syncing a template from a Git repository isn't modeled by Vyomi — use an S3 URL or upload a file instead." />}
          <FormField label="Amazon S3 template URL">
            <Box color="text-body-secondary">{s.templateSource === "s3url" && s.s3Url ? s.s3Url : "S3 URL: Will be generated when URL is provided"}</Box>
          </FormField>
        </SpaceBetween>
      </Container>
      {error && <ErrorAlert error={error} header="Couldn't read template" />}
    </SpaceBetween>
  );
}

function StackDetailsStep({ s, set, nameErr }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Provide a stack name</Header>}>
        <FormField label="Stack name" errorText={nameErr} constraintText="Up to 128 chars: letters (A-Z, a-z), numbers (0-9), dashes (-)">
          <Input value={s.stackName} onChange={({ detail }) => set({ stackName: detail.value })} ariaLabel="Stack name" />
        </FormField>
      </Container>
      <Container header={<Header variant="h2">Parameters</Header>}>
        <FormField label="Parameters" description="One input per template parameter">
          {s.paramDefs.length === 0 ? <Box color="text-body-secondary">This template has no parameters.</Box> : (
            <SpaceBetween size="m">
              {s.paramDefs.map((p) => (
                <FormField key={p.ParameterKey} label={p.ParameterKey} description={p.Description}>
                  <Input value={s.paramValues[p.ParameterKey] ?? ""} onChange={({ detail }) => set({ paramValues: { ...s.paramValues, [p.ParameterKey]: detail.value } })}
                    placeholder={p.DefaultValue} ariaLabel={p.ParameterKey} />
                </FormField>
              ))}
            </SpaceBetween>
          )}
        </FormField>
      </Container>
    </SpaceBetween>
  );
}

function StackOptionsStep({ s, set }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Tags - optional</Header>}>
        <FormField label="Tags" description="Key / Value pairs; up to 50 tags">
          <TagEditor tags={s.tags} onChange={({ detail }) => set({ tags: detail.tags })} />
        </FormField>
      </Container>
      <Container header={<Header variant="h2">Permissions - optional</Header>}>
        <FormField label="IAM role - optional">
          <Input value={s.iamRole} onChange={({ detail }) => set({ iamRole: detail.value })} placeholder="arn:aws:iam::123456789012:role/..." ariaLabel="IAM role - optional" />
        </FormField>
      </Container>
      <Container header={<Header variant="h2">Stack failure options</Header>}>
        <SpaceBetween size="l">
          <FormField label="Behavior on provisioning failure">
            <RadioGroup value={s.onFailure} onChange={({ detail }) => set({ onFailure: detail.value })} items={[
              { value: "ROLLBACK", label: "Roll back all stack resources" },
              { value: "DO_NOTHING", label: "Preserve successfully provisioned resources" },
            ]} />
          </FormField>
          <FormField label="Delete newly created resources during a rollback" description="Vyomi always deletes newly created resources on rollback; a deletion policy that preserves them isn't modeled.">
            <RadioGroup value={s.rollbackDeletion} onChange={({ detail }) => set({ rollbackDeletion: detail.value })} items={[
              { value: "policy", label: "Use deletion policy" },
              { value: "delete-all", label: "Delete all newly created resources" },
            ]} />
          </FormField>
        </SpaceBetween>
      </Container>
      <Container header={<Header variant="h2">Capabilities</Header>}>
        <Checkbox checked={s.capabilityAck} onChange={({ detail }) => set({ capabilityAck: detail.checked })}>
          I acknowledge that AWS CloudFormation might create IAM resources.
        </Checkbox>
      </Container>
      <ExpandableSection headerText="Advanced options">
        <SpaceBetween size="l">
          <FormField label="Stack policy" description="Stored and returned exactly as written; Vyomi doesn't enforce it.">
            <Textarea rows={4} value={s.stackPolicy} onChange={({ detail }) => set({ stackPolicy: detail.value })} spellcheck={false} ariaLabel="Stack policy" />
          </FormField>
          <FormField label="Rollback configuration" description="CloudWatch alarm-triggered rollback monitors — stored, not evaluated.">
            <Textarea rows={3} value={s.rollbackConfig} onChange={({ detail }) => set({ rollbackConfig: detail.value })} spellcheck={false} ariaLabel="Rollback configuration" />
          </FormField>
          <FormField label="Notification options" description="SNS topic ARNs to notify on stack events — stored, not published to.">
            <Input value={s.notificationOptions} onChange={({ detail }) => set({ notificationOptions: detail.value })} ariaLabel="Notification options" />
          </FormField>
          <FormField label="Termination protection">
            <RadioGroup value={s.terminationProtection} onChange={({ detail }) => set({ terminationProtection: detail.value })} items={[
              { value: "Deactivated", label: "Deactivated" }, { value: "Activated", label: "Activated" },
            ]} />
          </FormField>
          <FormField label="Timeout">
            <Input type="number" value={s.timeout} onChange={({ detail }) => set({ timeout: detail.value })} ariaLabel="Timeout" />
          </FormField>
        </SpaceBetween>
      </ExpandableSection>
    </SpaceBetween>
  );
}

function ReviewStep({ s, goto }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" actions={<a onClick={() => goto(1)} style={{ cursor: "pointer" }}>Edit</a>}>Review</Header>}>
        <SpaceBetween size="s">
          <div><Box variant="awsui-key-label">Stack name</Box><div>{s.stackName}</div></div>
          <div><Box variant="awsui-key-label">Template source</Box><div>{{ s3url: "Amazon S3 URL", upload: "Uploaded file", git: "Sync from Git" }[s.templateSource]}</div></div>
          <div><Box variant="awsui-key-label">Parameters</Box><div>{s.paramDefs.length ? s.paramDefs.map((p) => `${p.ParameterKey}=${s.paramValues[p.ParameterKey] || p.DefaultValue || ""}`).join(", ") : "None"}</div></div>
          <div><Box variant="awsui-key-label">Tags</Box><div>{s.tags.length ? s.tags.map((t) => `${t.key}=${t.value}`).join(", ") : "None"}</div></div>
          <div><Box variant="awsui-key-label">Capabilities</Box><div>{s.capabilityAck ? "CAPABILITY_NAMED_IAM" : "None"}</div></div>
          <div><Box variant="awsui-key-label">Termination protection</Box><div>{s.terminationProtection}</div></div>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );
}

const INITIAL = {
  prepareMode: "existing", templateSource: "s3url", s3Url: "", uploadedTemplate: "", uploadedName: "",
  templateBody: "", stackName: "", paramDefs: [], paramValues: {}, tags: [], iamRole: "",
  onFailure: "ROLLBACK", rollbackDeletion: "policy", capabilityAck: false,
  stackPolicy: "", rollbackConfig: "", notificationOptions: "", terminationProtection: "Deactivated", timeout: "",
};

export default function CreateStack() {
  const notify = useNotify();
  const [idx, setIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [nameTouched, setNameTouched] = useState(false);
  const [s, setS] = useState(INITIAL);
  const set = (patch) => setS((prev) => ({ ...prev, ...patch }));
  const nameErr = nameTouched && !/^[A-Za-z][A-Za-z0-9-]{0,127}$/.test(s.stackName) ? "Enter a valid stack name." : null;

  // Leaving step 0 ("Create stack"): resolve + validate the template so step 1 can
  // render the real per-template parameter inputs (ValidateTemplate is a real call).
  // A template that doesn't resolve/validate yet doesn't block moving on — like the
  // native wizard, the hard failure surfaces at Submit (api.createStack), never silently.
  const leaveTemplateStep = async () => {
    if (s.templateSource === "git" || s.prepareMode === "studio") return;
    setBusy(true);
    try {
      const body = s.templateSource === "upload" ? s.uploadedTemplate : undefined;
      const url = s.templateSource === "s3url" ? s.s3Url : undefined;
      const validated = await api.validateTemplate(body, url);
      set({ templateBody: body || "", templateUrl: url || "", paramDefs: validated.Parameters || [] });
    } catch (e) { set({ templateBody: s.templateSource === "upload" ? s.uploadedTemplate : "", templateUrl: s.templateSource === "s3url" ? s.s3Url : "", paramDefs: [] }); }
    finally { setBusy(false); }
  };

  const onNavigate = async ({ detail }) => {
    const forward = detail.requestedStepIndex > idx;
    setError(null);
    if (forward && idx === 0) await leaveTemplateStep();
    setIdx(detail.requestedStepIndex);
  };

  const finish = async () => {
    setNameTouched(true);
    if (!/^[A-Za-z][A-Za-z0-9-]{0,127}$/.test(s.stackName)) { setIdx(1); return; }
    setBusy(true); setError(null);
    try {
      await api.createStack({
        name: s.stackName, templateBody: s.templateBody || undefined, templateUrl: s.templateUrl || undefined,
        parameters: s.paramDefs.map((p) => ({ key: p.ParameterKey, value: s.paramValues[p.ParameterKey] ?? p.DefaultValue ?? "" })),
        tags: s.tags.filter((t) => t.key).map((t) => ({ key: t.key, value: t.value })),
        capabilities: s.capabilityAck ? ["CAPABILITY_NAMED_IAM"] : [],
        onFailure: s.onFailure, terminationProtection: s.terminationProtection === "Activated",
        roleArn: s.iamRole || undefined, timeoutInMinutes: s.timeout || undefined,
      });
      notify.success(`Creation of stack "${s.stackName}" has been initiated.`);
      navigate("cloudformation", "stacks", s.stackName);
    } catch (e) { setError(e); setIdx(2); } finally { setBusy(false); }
  };

  return (
    <Box padding={{ top: "l" }}>
      {error && idx !== 0 && <Box padding={{ horizontal: "l", bottom: "s" }}><ErrorAlert error={error} header="Couldn't create stack" /></Box>}
      <Wizard
        activeStepIndex={idx}
        onNavigate={onNavigate}
        onCancel={() => navigate("cloudformation", "stacks")}
        onSubmit={finish}
        isLoadingNextStep={busy}
        submitButtonText="Submit"
        i18nStrings={{ stepNumberLabel: (n) => `Step ${n}`, collapsedStepsLabel: (n, total) => `Step ${n} of ${total}`, cancelButton: "Cancel", previousButton: "Previous", nextButton: "Next", optional: "optional" }}
        steps={[
          { title: "Create stack", content: <CreateStackStep s={s} set={set} error={idx === 0 ? error : null} /> },
          { title: "Specify stack details", content: <StackDetailsStep s={s} set={set} nameErr={nameErr} /> },
          { title: "Configure stack options", content: <StackOptionsStep s={s} set={set} /> },
          { title: "Review and create", content: <ReviewStep s={s} goto={setIdx} /> },
        ]}
      />
    </Box>
  );
}
