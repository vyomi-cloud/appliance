/* Create key — 6-step wizard matching the native console. Steps 1-2 (type/usage/spec,
 * alias/description/tags) and the policy editor in step 5 are real; the IAM-principal
 * pickers in steps 3-4 are the one declared gap (core/capabilities/aws/kms.json:
 * kms.key-administrators) — the SAME gap as the key detail page's Key policy tab. */
import { useState } from "react";
import Wizard from "@cloudscape-design/components/wizard";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Tiles from "@cloudscape-design/components/tiles";
import Checkbox from "@cloudscape-design/components/checkbox";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, NotSimulated, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

const ASYMMETRIC_SPECS = ["RSA_2048", "RSA_3072", "RSA_4096", "ECC_NIST_P256", "ECC_NIST_P384", "ECC_NIST_P521", "ECC_SECG_P256K1", "ML_DSA_44", "ML_DSA_65", "ML_DSA_87"];
const HMAC_SPECS = ["HMAC_224", "HMAC_256", "HMAC_384", "HMAC_512"];
const DEFAULT_POLICY = (accountId) => JSON.stringify({ Version: "2012-10-17", Id: "key-default-1", Statement: [
  { Sid: "Enable IAM User Permissions", Effect: "Allow", Principal: { AWS: `arn:aws:iam::${accountId}:root` }, Action: "kms:*", Resource: "*" },
] }, null, 2);

function ConfigureKeyStep({ s, set }) {
  const specOptions = (s.keyType === "Asymmetric" ? ASYMMETRIC_SPECS : s.keyUsageSym === "Generate and verify MAC" ? HMAC_SPECS : null);
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Key type</Header>}>
        <RadioGroup value={s.keyType} onChange={({ detail }) => set({ keyType: detail.value })}
          items={[{ value: "Symmetric", label: "Symmetric" }, { value: "Asymmetric", label: "Asymmetric" }]} />
      </Container>
      <Container header={<Header variant="h2">Key usage</Header>}>
        {s.keyType === "Symmetric" ? (
          <RadioGroup value={s.keyUsageSym} onChange={({ detail }) => set({ keyUsageSym: detail.value })}
            items={[{ value: "Encrypt and decrypt", label: "Encrypt and decrypt" }, { value: "Generate and verify MAC", label: "Generate and verify MAC" }]} />
        ) : (
          <RadioGroup value={s.keyUsageAsym} onChange={({ detail }) => set({ keyUsageAsym: detail.value })}
            items={[{ value: "Encrypt and decrypt", label: "Encrypt and decrypt" }, { value: "Sign and verify", label: "Sign and verify" }, { value: "Key agreement", label: "Key agreement" }]} />
        )}
      </Container>
      {specOptions && (
        <Container header={<Header variant="h2">Key spec</Header>}>
          <RadioGroup value={s.keySpec} onChange={({ detail }) => set({ keySpec: detail.value })} items={specOptions.map((v) => ({ value: v, label: v }))} />
        </Container>
      )}
      <ExpandableSection headerText="Advanced options">
        <SpaceBetween size="l">
          <FormField label="Key material origin">
            <Tiles value={s.origin} onChange={({ detail }) => set({ origin: detail.value })} columns={1} items={[
              { value: "KMS", label: "KMS - recommended", description: "Vyomi generates and manages the key material." },
              { value: "EXTERNAL", label: "External (Import Key material)", description: "Vyomi stores key material you provide." },
              { value: "CLOUDHSM", label: "AWS CloudHSM key store", disabled: true, description: "Requires a connected custom key store." },
              { value: "XKS", label: "External key store", disabled: true, description: "Requires a connected custom key store." },
            ]} />
            {(s.origin === "CLOUDHSM" || s.origin === "XKS") && <NotSimulated feature="Custom key stores" note="Connecting a custom key store always fails in Vyomi — there's no real CloudHSM cluster or external XKS proxy to reach." />}
          </FormField>
          <FormField label="Regionality">
            <Tiles value={s.regionality} onChange={({ detail }) => set({ regionality: detail.value })} columns={1} items={[
              { value: "SINGLE", label: "Single-Region key" },
              { value: "MULTI", label: "Multi-Region key", disabled: true, description: "Multi-Region replica keys aren't modeled by Vyomi." },
            ]} />
          </FormField>
        </SpaceBetween>
      </ExpandableSection>
    </SpaceBetween>
  );
}

function LabelsStep({ s, set, aliasErr }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Alias</Header>}>
        <FormField label="Alias" errorText={aliasErr} constraintText="Letters, numbers, '/', '_', '-'; cannot begin with aws/">
          <Input value={s.alias} onChange={({ detail }) => set({ alias: detail.value })} placeholder="Enter alias" ariaLabel="Alias" />
        </FormField>
      </Container>
      <Container header={<Header variant="h2">Description - optional</Header>}>
        <FormField label="Description">
          <Textarea value={s.description} onChange={({ detail }) => set({ description: detail.value })} placeholder="Description of the key" ariaLabel="Description" />
        </FormField>
      </Container>
      <Container header={<Header variant="h2">Tags - optional</Header>}>
        <FormField label="Tags">
          <TagEditor tags={s.tags} onChange={({ detail }) => set({ tags: detail.tags })} />
        </FormField>
      </Container>
    </SpaceBetween>
  );
}

function AdminPermissionsStep({ s, set }) {
  return (
    <SpaceBetween size="l">
      <NotSimulatedContainer title="Key administrators" feature="IAM key-administrator picker" note="Select IAM users and roles who can administer this key — not modeled; manage via the policy JSON in the Edit-key-policy step that follows." />
      <Container header={<Header variant="h2">Key deletion</Header>}>
        <Checkbox checked disabled>Allow key administrators to delete this key</Checkbox>
      </Container>
    </SpaceBetween>
  );
}

function UsagePermissionsStep() {
  return (
    <SpaceBetween size="l">
      <NotSimulatedContainer title="This account" feature="Key users" note="Select IAM users and roles who can use this key — not modeled; manage via the policy JSON in the Edit-key-policy step that follows." />
      <NotSimulatedContainer title="Other AWS accounts" feature="Other AWS accounts" />
    </SpaceBetween>
  );
}

function PolicyStep({ s, set }) {
  return (
    <Container header={<Header variant="h2">Key policy</Header>}>
      <FormField label="Key policy" description="JSON policy editor — stored and returned exactly as written; Vyomi doesn't evaluate it.">
        <Textarea rows={16} value={s.policy} onChange={({ detail }) => set({ policy: detail.value })} spellcheck={false} />
      </FormField>
    </Container>
  );
}

function ReviewStep({ s, goto }) {
  const usage = s.keyType === "Symmetric" ? s.keyUsageSym : s.keyUsageAsym;
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" actions={<a onClick={() => goto(0)} style={{ cursor: "pointer" }}>Edit</a>}>Key configuration</Header>}>
        <SpaceBetween size="s">
          <div><Box variant="awsui-key-label">Key type</Box><div>{s.keyType}</div></div>
          <div><Box variant="awsui-key-label">Key spec</Box><div>{s.keySpec || (s.keyType === "Symmetric" ? "SYMMETRIC_DEFAULT" : "-")}</div></div>
          <div><Box variant="awsui-key-label">Key usage</Box><div>{usage}</div></div>
          <div><Box variant="awsui-key-label">Origin</Box><div>{s.origin === "EXTERNAL" ? "External (Import Key material)" : "KMS - recommended"}</div></div>
          <div><Box variant="awsui-key-label">Regionality</Box><div>Single-Region key</div></div>
        </SpaceBetween>
      </Container>
      <Container header={<Header variant="h2" actions={<a onClick={() => goto(1)} style={{ cursor: "pointer" }}>Edit</a>}>Alias and description</Header>}>
        <SpaceBetween size="s">
          <div><Box variant="awsui-key-label">Alias</Box><div>{s.alias}</div></div>
          <div><Box variant="awsui-key-label">Description</Box><div>{s.description || "-"}</div></div>
        </SpaceBetween>
      </Container>
      <Container header={<Header variant="h2" actions={<a onClick={() => goto(1)} style={{ cursor: "pointer" }}>Edit</a>}>Tags</Header>}>
        {s.tags.length ? s.tags.map((t) => <div key={t.key}>{t.key} = {t.value}</div>) : <Box color="text-body-secondary">No tags</Box>}
      </Container>
      <Container header={<Header variant="h2" actions={<a onClick={() => goto(4)} style={{ cursor: "pointer" }}>Edit</a>}>Key policy</Header>}>
        <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{s.policy}</pre></Box>
      </Container>
    </SpaceBetween>
  );
}

export default function CreateKey() {
  const notify = useNotify();
  const [idx, setIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);
  const [s, setS] = useState({
    keyType: "Symmetric", keyUsageSym: "Encrypt and decrypt", keyUsageAsym: "Encrypt and decrypt",
    keySpec: "", origin: "KMS", regionality: "SINGLE",
    alias: "", description: "", tags: [], policy: DEFAULT_POLICY("123456789012"),
  });
  const set = (patch) => setS((prev) => ({ ...prev, ...patch }));
  const aliasErr = touched && (!s.alias || /^aws\//.test(s.alias)) ? "Alias is required and cannot begin with aws/." : null;

  const finish = async () => {
    setTouched(true);
    if (!s.alias || /^aws\//.test(s.alias)) { setIdx(1); return; }
    setBusy(true); setError(null);
    try {
      const usage = s.keyType === "Symmetric"
        ? (s.keyUsageSym === "Generate and verify MAC" ? "GENERATE_VERIFY_MAC" : "ENCRYPT_DECRYPT")
        : ({ "Encrypt and decrypt": "ENCRYPT_DECRYPT", "Sign and verify": "SIGN_VERIFY", "Key agreement": "KEY_AGREEMENT" }[s.keyUsageAsym]);
      const spec = s.keyType === "Symmetric" ? (s.keyUsageSym === "Generate and verify MAC" ? (s.keySpec || "HMAC_256") : "SYMMETRIC_DEFAULT") : (s.keySpec || "RSA_2048");
      const md = await api.createKey({
        KeyUsage: usage, KeySpec: spec, Origin: s.origin === "EXTERNAL" ? "EXTERNAL" : "AWS_KMS",
        Description: s.description, Policy: s.policy,
        Tags: s.tags.filter((t) => !t.markedForRemoval && t.key).map((t) => ({ TagKey: t.key, TagValue: t.value || "" })),
      });
      await api.createAlias(`alias/${s.alias}`, md.KeyId);
      notify.success(`Key "${s.alias}" created.`);
      navigate("kms", "customer-managed-keys", md.KeyId);
    } catch (e) { setError(e); setIdx(5); } finally { setBusy(false); }
  };

  const steps = [
    { title: "Configure key", content: <ConfigureKeyStep s={s} set={set} /> },
    { title: "Add labels", content: <LabelsStep s={s} set={set} aliasErr={aliasErr} /> },
    { title: "Define key administrative permissions", content: <AdminPermissionsStep s={s} set={set} /> },
    { title: "Define key usage permissions", content: <UsagePermissionsStep /> },
    { title: "Edit key policy", content: <PolicyStep s={s} set={set} /> },
    { title: "Review", content: <ReviewStep s={s} goto={setIdx} /> },
  ];

  return (
    <Box padding={{ top: "l" }}>
      {error && <Box padding={{ horizontal: "l", bottom: "s" }}><ErrorAlert error={error} header="Couldn't create key" /></Box>}
      <Wizard
        activeStepIndex={idx}
        onNavigate={({ detail }) => setIdx(detail.requestedStepIndex)}
        onCancel={() => navigate("kms", "customer-managed-keys")}
        onSubmit={finish}
        isLoadingNextStep={busy}
        submitButtonText="Finish"
        i18nStrings={{
          stepNumberLabel: (n) => `Step ${n}`,
          collapsedStepsLabel: (n, total) => `Step ${n} of ${total}`,
          cancelButton: "Cancel", previousButton: "Previous", nextButton: "Next", optional: "optional",
        }}
        steps={steps}
      />
    </Box>
  );
}
