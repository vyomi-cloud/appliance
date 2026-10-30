/* Store a new secret — 4-step wizard matching the native console. Secret type / credentials
 * / key-value-or-plaintext value / secret name & description / tags / resource policy /
 * rotation schedule are all real; the database-instance picker, the "Managed external
 * secret" type and cross-Region replication are declared gaps (core/capabilities/aws/
 * secretsmanager.json), and automatic rotation never fires on its own (no Lambda runtime,
 * no scheduler — the same honesty posture as kms.key.rotation). */
import { useEffect, useState } from "react";
import Wizard from "@cloudscape-design/components/wizard";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Checkbox from "@cloudscape-design/components/checkbox";
import Select from "@cloudscape-design/components/select";
import Toggle from "@cloudscape-design/components/toggle";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import Tabs from "@cloudscape-design/components/tabs";
import TagEditor from "@cloudscape-design/components/tag-editor";
import Modal from "@cloudscape-design/components/modal";
import Button from "@cloudscape-design/components/button";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, NotSimulatedContainer } from "../../kit/common.jsx";
import KeyValueOrPlaintext from "./KeyValueOrPlaintext.jsx";
import * as api from "./api.js";

const DB_TYPES = [
  "Credentials for Amazon RDS database",
  "Credentials for Amazon DocumentDB database",
  "Credentials for Amazon Redshift data warehouse",
  "Credentials for other database",
];
const SECRET_TYPES = [...DB_TYPES, "Managed external secret", "Other type of secret"];
const SAMPLE = (name) => ({
  Java: `GetSecretValueRequest request = GetSecretValueRequest.builder().secretId("${name}").build();\nString secret = client.getSecretValue(request).secretString();`,
  JavaScript: `const data = await client.send(new GetSecretValueCommand({ SecretId: "${name}" }));\nconst secret = data.SecretString;`,
  "C#": `var response = await client.GetSecretValueAsync(new GetSecretValueRequest { SecretId = "${name}" });\nvar secret = response.SecretString;`,
  Python3: `secret = client.get_secret_value(SecretId="${name}")["SecretString"]`,
  Ruby: `secret = client.get_secret_value(secret_id: "${name}").secret_string`,
  Go: `out, err := svc.GetSecretValue(ctx, &secretsmanager.GetSecretValueInput{SecretId: aws.String("${name}")})`,
  Rust: `let resp = client.get_secret_value().secret_id("${name}").send().await?;`,
});

function SecretTypeStep({ s, set, dbAliases }) {
  const isDb = DB_TYPES.includes(s.secretType);
  const isOtherDb = s.secretType === "Credentials for other database";
  const isManaged = s.secretType === "Managed external secret";
  const isOther = s.secretType === "Other type of secret";
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Secret type</Header>}>
        <FormField label="Secret type">
          <RadioGroup value={s.secretType} onChange={({ detail }) => set({ secretType: detail.value })}
            items={SECRET_TYPES.map((v) => ({ value: v, label: v }))} />
        </FormField>
      </Container>
      {isManaged && <NotSimulatedContainer title="Managed external secret"
        note="Managed external secrets are provisioned on your behalf by another AWS service (e.g. Amazon Redshift, RDS Managed Secrets) — Vyomi doesn't model that provisioning flow. Store the credential manually using 'Other type of secret' instead." />}
      {(isDb || isOther) && (
        <Container header={<Header variant="h2">{isOther ? "Key/value pairs" : "Credentials"}</Header>}>
          {isOther ? (
            <KeyValueOrPlaintext tab={s.valueTab} setTab={(v) => set({ valueTab: v })}
              pairs={s.kvPairs} setPairs={(v) => set({ kvPairs: v })}
              plaintext={s.plaintext} setPlaintext={(v) => set({ plaintext: v })} />
          ) : (
            <SpaceBetween size="m">
              <FormField label="User name"><Input value={s.username} onChange={({ detail }) => set({ username: detail.value })} ariaLabel="User name" /></FormField>
              <FormField label="Password">
                <Input type={s.showPassword ? "text" : "password"} value={s.password} onChange={({ detail }) => set({ password: detail.value })} ariaLabel="Password" />
              </FormField>
              <Checkbox checked={s.showPassword} onChange={({ detail }) => set({ showPassword: detail.checked })}>Show password</Checkbox>
            </SpaceBetween>
          )}
        </Container>
      )}
      {isOtherDb && (
        <Container header={<Header variant="h2">Database</Header>}>
          <SpaceBetween size="m">
            <FormField label="Database engine">
              <RadioGroup value={s.dbEngine} onChange={({ detail }) => set({ dbEngine: detail.value })}
                items={["MariaDB", "MySQL", "PostgreSQL", "Oracle", "Microsoft SQL Server"].map((v) => ({ value: v, label: v }))} />
            </FormField>
            <FormField label="Server address"><Input value={s.serverAddress} onChange={({ detail }) => set({ serverAddress: detail.value })} ariaLabel="Server address" /></FormField>
            <FormField label="Database name"><Input value={s.dbName} onChange={({ detail }) => set({ dbName: detail.value })} ariaLabel="Database name" /></FormField>
            <FormField label="Port"><Input type="number" value={s.port} onChange={({ detail }) => set({ port: detail.value })} ariaLabel="Port" /></FormField>
          </SpaceBetween>
        </Container>
      )}
      {isDb && !isOtherDb && (
        <NotSimulatedContainer title="Database" feature="Database instance picker"
          note="Browsing and selecting an existing RDS/DocumentDB/Redshift database instance isn't modeled — enter the connecting credentials above and connect to your database manually." />
      )}
      <Container header={<Header variant="h2">Encryption key</Header>}>
        <FormField label="Encryption key" description="KMS key Vyomi creates, or a customer managed KMS key.">
          <Select selectedOption={{ label: s.kmsKeyId, value: s.kmsKeyId }}
            onChange={({ detail }) => set({ kmsKeyId: detail.selectedOption.value })}
            options={[{ label: "aws/secretsmanager", value: "aws/secretsmanager" }, ...dbAliases.map((a) => ({ label: a, value: a }))]} />
        </FormField>
      </Container>
    </SpaceBetween>
  );
}

function ConfigureSecretStep({ s, set, nameErr }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Secret name and description</Header>}>
        <SpaceBetween size="m">
          <FormField label="Secret name" errorText={nameErr} constraintText="Alphanumeric characters and /_+=.@- only.">
            <Input value={s.name} onChange={({ detail }) => set({ name: detail.value })} placeholder="prod/AppBeta/MySql" ariaLabel="Secret name" />
          </FormField>
          <FormField label="Description - optional" constraintText="Maximum 250 characters.">
            <Textarea value={s.description} onChange={({ detail }) => set({ description: detail.value })} placeholder="Access to MYSQL prod database for my AppBeta" ariaLabel="Description" />
          </FormField>
        </SpaceBetween>
      </Container>
      <Container header={<Header variant="h2">Tags - optional</Header>}>
        <FormField label="Tags"><TagEditor tags={s.tags} onChange={({ detail }) => set({ tags: detail.tags })} /></FormField>
      </Container>
      <Container header={<Header variant="h2" actions={<Button onClick={() => set({ editPolicy: true })}>Edit permissions</Button>}>Resource permissions - optional</Header>}>
        {s.resourcePolicy ? <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{s.resourcePolicy}</pre></Box> : <Box color="text-body-secondary">No resource policy attached.</Box>}
      </Container>
      <NotSimulatedContainer title="Replicate secret - optional"
        note="Creating read-only replicas of this secret in another AWS Region isn't modeled — there's no second Region's store to replicate into. Encryption key selection for a replica isn't applicable." />
      <Modal visible={!!s.editPolicy} onDismiss={() => set({ editPolicy: false })} size="large" header="Edit resource permissions"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => set({ editPolicy: false })}>Cancel</Button>
          <Button variant="primary" onClick={() => set({ editPolicy: false })}>Save changes</Button>
        </SpaceBetween></Box>}>
        <FormField label="Resource policy" description="JSON policy editor — stored and returned exactly as written; Vyomi doesn't evaluate it.">
          <Textarea rows={14} value={s.resourcePolicy} onChange={({ detail }) => set({ resourcePolicy: detail.value })} spellcheck={false} />
        </FormField>
      </Modal>
    </SpaceBetween>
  );
}

function ConfigureRotationStep({ s, set }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Configure automatic rotation</Header>}>
        <SpaceBetween size="m">
          <Toggle checked={s.rotation} onChange={({ detail }) => set({ rotation: detail.checked })}>Automatic rotation</Toggle>
          {s.rotation && (
            <>
              <FormField label="Rotation schedule">
                <RadioGroup value={s.rotationScheduleType} onChange={({ detail }) => set({ rotationScheduleType: detail.value })}
                  items={[{ value: "builder", label: "Schedule expression builder" }, { value: "expression", label: "Schedule expression" }]} />
              </FormField>
              {s.rotationScheduleType === "builder" ? (
                <FormField label="Time unit">
                  <Select selectedOption={{ label: s.timeUnit, value: s.timeUnit }}
                    onChange={({ detail }) => set({ timeUnit: detail.selectedOption.value })}
                    options={["Hours", "Days", "Weeks", "Months"].map((v) => ({ label: v, value: v }))} />
                </FormField>
              ) : (
                <FormField label="Schedule expression"><Input value={s.scheduleExpression} onChange={({ detail }) => set({ scheduleExpression: detail.value })} placeholder="rate(30 days)" ariaLabel="Schedule expression" /></FormField>
              )}
              <FormField label="Window duration - optional"><Input value={s.windowDuration} onChange={({ detail }) => set({ windowDuration: detail.value })} placeholder="3h" ariaLabel="Window duration" /></FormField>
              <Checkbox checked={s.rotateImmediately} onChange={({ detail }) => set({ rotateImmediately: detail.checked })}>
                Rotate immediately when the secret is stored. The next rotation will begin on your schedule.
              </Checkbox>
            </>
          )}
        </SpaceBetween>
      </Container>
      {s.rotation && (
        <NotSimulatedContainer title="Rotation function" feature="Lambda rotation function"
          note="Rotation normally invokes a Lambda rotation function to generate the new secret value. Vyomi has no Lambda runtime wired to Secrets Manager, so 'Rotate immediately' carries the current value forward into a fresh version — the same AWSCURRENT/AWSPREVIOUS transition a real rotation performs — without a Lambda step. Create function isn't available." />
      )}
    </SpaceBetween>
  );
}

function ReviewStep({ s, goto, name }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" actions={<a onClick={() => goto(0)} style={{ cursor: "pointer" }}>Edit</a>}>Step 1: Choose secret type</Header>}>
        <Box><Box variant="awsui-key-label">Secret type</Box><div>{s.secretType}</div></Box>
      </Container>
      <Container header={<Header variant="h2" actions={<a onClick={() => goto(1)} style={{ cursor: "pointer" }}>Edit</a>}>Step 2: Configure secret</Header>}>
        <Box><Box variant="awsui-key-label">Secret name</Box><div>{s.name || "-"}</div></Box>
      </Container>
      <Container header={<Header variant="h2" actions={<a onClick={() => goto(2)} style={{ cursor: "pointer" }}>Edit</a>}>Step 3: Configure rotation - optional</Header>}>
        <Box><Box variant="awsui-key-label">Automatic rotation</Box><div>{s.rotation ? "Enabled" : "Disabled"}</div></Box>
      </Container>
      <Container header={<Header variant="h2">Sample code</Header>}>
        <Tabs tabs={Object.entries(SAMPLE(name || s.name || "secret-name")).map(([lang, code]) => ({
          id: lang, label: lang, content: <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{code}</pre></Box>,
        }))} />
      </Container>
    </SpaceBetween>
  );
}

export default function StoreSecret() {
  const notify = useNotify();
  const [idx, setIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);
  const [dbAliases, setDbAliases] = useState([]);
  const [s, setS] = useState({
    secretType: "Credentials for Amazon RDS database",
    username: "", password: "", showPassword: false,
    dbEngine: "MySQL", serverAddress: "", dbName: "", port: "",
    valueTab: "keyvalue", kvPairs: [{ key: "", value: "" }], plaintext: "",
    kmsKeyId: "aws/secretsmanager",
    name: "", description: "", tags: [], resourcePolicy: "", editPolicy: false,
    rotation: false, rotationScheduleType: "builder", timeUnit: "Months", scheduleExpression: "", windowDuration: "", rotateImmediately: true,
  });
  const set = (patch) => setS((prev) => ({ ...prev, ...patch }));
  const nameErr = touched && !s.name ? "Secret name is required." : null;

  useEffect(() => {
    api.listKmsAliases().then((aliases) => setDbAliases(aliases.filter((a) => a !== "aws/secretsmanager"))).catch(() => {});
  }, []);

  const secretValue = () => {
    const isDb = DB_TYPES.includes(s.secretType);
    const isOtherDb = s.secretType === "Credentials for other database";
    if (isDb) {
      const v = { username: s.username, password: s.password };
      if (isOtherDb) Object.assign(v, { engine: s.dbEngine, host: s.serverAddress, dbname: s.dbName, port: s.port });
      return JSON.stringify(v);
    }
    if (s.secretType === "Other type of secret") {
      if (s.valueTab === "plaintext") return s.plaintext;
      return JSON.stringify(Object.fromEntries(s.kvPairs.filter((p) => p.key).map((p) => [p.key, p.value])));
    }
    return "{}";
  };

  const finish = async () => {
    setTouched(true);
    if (!s.name) { setIdx(1); return; }
    setBusy(true); setError(null);
    try {
      await api.createSecret({
        Name: s.name, Description: s.description, SecretString: secretValue(), KmsKeyId: s.kmsKeyId,
        Tags: s.tags.filter((t) => !t.markedForRemoval && t.key).map((t) => ({ Key: t.key, Value: t.value || "" })),
      });
      if (s.resourcePolicy) await api.putResourcePolicy(s.name, s.resourcePolicy);
      if (s.rotation) {
        const rules = s.rotationScheduleType === "expression"
          ? { ScheduleExpression: s.scheduleExpression || "rate(30 days)" }
          : { AutomaticallyAfterDays: { Hours: 1 / 24, Days: 1, Weeks: 7, Months: 30 }[s.timeUnit] || 30 };
        if (s.windowDuration) rules.Duration = s.windowDuration;
        await api.rotateSecret(s.name, { RotationRules: rules, RotateImmediately: s.rotateImmediately });
      }
      notify.success(`Successfully stored secret "${s.name}".`);
      navigate("secretsmanager", "secret", s.name);
    } catch (e) { setError(e); setIdx(3); } finally { setBusy(false); }
  };

  const steps = [
    { title: "Choose secret type", content: <SecretTypeStep s={s} set={set} dbAliases={dbAliases} /> },
    { title: "Configure secret", content: <ConfigureSecretStep s={s} set={set} nameErr={nameErr} /> },
    { title: "Configure rotation", content: <ConfigureRotationStep s={s} set={set} /> },
    { title: "Review", content: <ReviewStep s={s} goto={setIdx} name={s.name} /> },
  ];

  return (
    <Box padding={{ top: "l" }}>
      {error && <Box padding={{ horizontal: "l", bottom: "s" }}><ErrorAlert error={error} header="Couldn't store secret" /></Box>}
      <Wizard
        activeStepIndex={idx}
        onNavigate={({ detail }) => setIdx(detail.requestedStepIndex)}
        onCancel={() => navigate("secretsmanager", "listsecrets")}
        onSubmit={finish}
        isLoadingNextStep={busy}
        submitButtonText="Store"
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
