/* Update stack — not a distinct native-console page in the spec (it's the "Update
 * stack" action on Stacks/stack detail), so it's a focused form rather than the
 * 4-step Create-stack wizard: current template shown, replace it or keep it, adjust
 * parameters/tags/capabilities, UpdateStack. */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Textarea from "@cloudscape-design/components/textarea";
import Checkbox from "@cloudscape-design/components/checkbox";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import Spinner from "@cloudscape-design/components/spinner";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function UpdateStack({ params }) {
  const name = params.name;
  const notify = useNotify();
  const t = useAsync(() => api.describeStack(name), [name]);
  const [usePrevious, setUsePrevious] = useState(true);
  const [template, setTemplate] = useState("");
  const [paramDefs, setParamDefs] = useState(null);
  const [paramValues, setParamValues] = useState({});
  const [tags, setTags] = useState([]);
  const [capabilityAck, setCapabilityAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const d = t.data;

  const loadCurrentTemplate = async () => {
    const body = await api.getTemplate(name);
    setTemplate(body);
    setUsePrevious(false);
  };

  const validate = async () => {
    setError(null);
    try {
      const r = await api.validateTemplate(usePrevious ? await api.getTemplate(name) : template);
      setParamDefs(r.Parameters || []);
      const seeded = {};
      (r.Parameters || []).forEach((p) => { seeded[p.ParameterKey] = d.Parameters?.[p.ParameterKey] ?? p.DefaultValue ?? ""; });
      setParamValues(seeded);
      setTags(Object.entries(d.Tags || {}).map(([key, value]) => ({ key, value })));
    } catch (e) { setError(e); }
  };

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.updateStack({
        name, usePreviousTemplate: usePrevious, templateBody: usePrevious ? undefined : template,
        parameters: (paramDefs || []).map((p) => ({ key: p.ParameterKey, value: paramValues[p.ParameterKey] ?? "" })),
        tags: tags.filter((x) => x.key).map((x) => ({ key: x.key, value: x.value })),
        capabilities: capabilityAck ? ["CAPABILITY_NAMED_IAM"] : [],
      });
      notify.success(`Update of stack "${name}" has been initiated.`);
      navigate("cloudformation", "stacks", name);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Update stack: {name}</Header>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <Container header={<Header variant="h2">Template</Header>}>
          <SpaceBetween size="l">
            <Checkbox checked={usePrevious} onChange={({ detail }) => setUsePrevious(detail.checked)}>Use current template</Checkbox>
            {!usePrevious && (
              <FormField label="New template">
                <Textarea rows={12} value={template} onChange={({ detail }) => setTemplate(detail.value)} spellcheck={false} ariaLabel="New template" />
              </FormField>
            )}
            <Button onClick={loadCurrentTemplate}>Load current template to edit</Button>
          </SpaceBetween>
        </Container>
        {paramDefs === null ? (
          <Button onClick={validate}>Next: review parameters</Button>
        ) : (
          <>
            <Container header={<Header variant="h2">Parameters</Header>}>
              {paramDefs.length === 0 ? <Box color="text-body-secondary">This template has no parameters.</Box> : (
                <SpaceBetween size="m">
                  {paramDefs.map((p) => (
                    <FormField key={p.ParameterKey} label={p.ParameterKey}>
                      <Input value={paramValues[p.ParameterKey] ?? ""} onChange={({ detail }) => setParamValues((v) => ({ ...v, [p.ParameterKey]: detail.value }))} ariaLabel={p.ParameterKey} />
                    </FormField>
                  ))}
                </SpaceBetween>
              )}
            </Container>
            <Container header={<Header variant="h2">Tags</Header>}>
              <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} />
            </Container>
            <Container header={<Header variant="h2">Capabilities</Header>}>
              <Checkbox checked={capabilityAck} onChange={({ detail }) => setCapabilityAck(detail.checked)}>I acknowledge that AWS CloudFormation might create IAM resources.</Checkbox>
            </Container>
            <Box float="right"><SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => navigate("cloudformation", "stacks", name)}>Cancel</Button>
              <Button variant="primary" loading={busy} onClick={submit}>Update stack</Button>
            </SpaceBetween></Box>
          </>
        )}
      </SpaceBetween>
    </ContentLayout>
  );
}
