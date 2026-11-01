/* Create parameter — one form, real PutParameter. SecureString encrypts through the real
 * KMS core (core/ssm_core.py's PutParameter, kms_store wired in core/aws_wire_router.py). */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateParameter() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tier, setTier] = useState("Standard");
  const [type, setType] = useState("String");
  const [value, setValue] = useState("");
  const [keyId, setKeyId] = useState("alias/aws/ssm");
  const [pattern, setPattern] = useState("");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);

  const nameErr = touched && !name ? "Enter a parameter name." : null;

  const submit = async () => {
    setTouched(true);
    if (!name || !value) return;
    setBusy(true); setError(null);
    try {
      await api.putParameter({
        Name: name, Value: value, Type: type, Tier: tier,
        ...(description ? { Description: description } : {}),
        ...(pattern ? { AllowedPattern: pattern } : {}),
        ...(type === "SecureString" ? { KeyId: keyId } : {}),
        ...(tags.length ? { Tags: tags.filter((t) => !t.markedForRemoval && t.key).map(({ key, value: v }) => ({ Key: key, Value: v })) } : {}),
      });
      notify.success(`Successfully created parameter "${name}"`);
      location.hash = `${href("ssm", "parameters", "view").slice(1)}?name=${encodeURIComponent(name)}`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create parameter</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button formAction="none" variant="link" href="#/ssm/parameters" onFollow={follow}>Cancel</Button>
              <Button variant="primary" loading={busy}>Create parameter</Button>
            </SpaceBetween>
          }
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Parameter details</Header>}>
              <SpaceBetween size="l">
                <FormField label="Name" errorText={nameErr} constraintText="A-z 0-9 and _ . - / only. Up to 15 hierarchy levels; can't start with aws or ssm.">
                  <Input value={name} placeholder="/vyomi/app/config" onChange={({ detail }) => setName(detail.value)} onBlur={() => setTouched(true)} ariaLabel="Name" />
                </FormField>
                <FormField label="Description - optional">
                  <Textarea value={description} onChange={({ detail }) => setDescription(detail.value)} />
                </FormField>
                <FormField label="Tier">
                  <RadioGroup value={tier} onChange={({ detail }) => setTier(detail.value)} items={[
                    { value: "Standard", label: "Standard", description: "Up to 4,096 characters, no additional charge." },
                    { value: "Advanced", label: "Advanced", description: "Up to 8,192 characters." },
                    { value: "Intelligent-Tiering", label: "Intelligent-Tiering", description: "Vyomi picks Standard or Advanced for you, based on size and policies." },
                  ]} />
                </FormField>
              </SpaceBetween>
            </Container>
            <Container header={<Header variant="h2">Value</Header>}>
              <SpaceBetween size="l">
                <FormField label="Type">
                  <RadioGroup value={type} onChange={({ detail }) => setType(detail.value)} items={[
                    { value: "String", label: "String" },
                    { value: "StringList", label: "StringList" },
                    { value: "SecureString", label: "SecureString" },
                  ]} />
                </FormField>
                {type === "SecureString" && (
                  <FormField label="KMS key source" description="The key protecting this parameter's value. Encrypted for real through the KMS core.">
                    <Input value={keyId} onChange={({ detail }) => setKeyId(detail.value)} placeholder="alias/aws/ssm" ariaLabel="KMS key source" />
                  </FormField>
                )}
                <FormField label="Allowed pattern - optional" description="A regular expression the value must match.">
                  <Input value={pattern} onChange={({ detail }) => setPattern(detail.value)} placeholder="^[a-zA-Z0-9]+$" />
                </FormField>
                <FormField label="Value" errorText={touched && !value ? "Enter a value." : null}>
                  <Textarea rows={6} value={value} onChange={({ detail }) => setValue(detail.value)} onBlur={() => setTouched(true)} spellcheck={false} ariaLabel="Value" />
                </FormField>
              </SpaceBetween>
            </Container>
            <Container header={<Header variant="h2" counter={`(${tags.filter((t) => !t.markedForRemoval).length})`}>Tags - optional</Header>}>
              <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} />
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
