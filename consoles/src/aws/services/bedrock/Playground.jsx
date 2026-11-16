/* Bedrock > Playground (capture 009): "Select a model to get started" empty state, then a chat with a configurations panel.
 * Every turn is a real Converse call to the local-LLM seam through the Bedrock Runtime wire. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Grid from "@cloudscape-design/components/grid";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Slider from "@cloudscape-design/components/slider";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Textarea from "@cloudscape-design/components/textarea";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";
import * as tuneApi from "./inferTune/api.js";
import { ServingBar } from "./inferTune/ImportedModels.jsx";
import { modelOption, ModelPicker } from "./Common.jsx";

export default function Playground() {
  const models = useAsync(() => api.listModels(), []);
  const imported = useAsync(() => tuneApi.listImportedModels().catch(() => []), []);
  const [model, setModel] = useState(null);
  const [system, setSystem] = useState("");
  const [prompt, setPrompt] = useState("Say hello in five words.");
  const [temp, setTemp] = useState(0.5);
  const [maxTok, setMaxTok] = useState("256");
  const [turns, setTurns] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const found = (models.data || []).filter((m) => m.outputModalities?.includes("TEXT")).map(modelOption);
  const mine = (imported.data || []).map((m) => ({ label: m.modelName, value: m.modelArn, description: m.modelArn, tags: ["Imported", "Your LoRA adapter"] }));
  const opts = mine.length ? [{ label: "Imported models (your LoRA adapters)", options: mine }, { label: "Foundation models", options: found }] : found;
  const isImported = !!model && String(model.value).includes(":imported-model/");
  const run = async () => {
    setBusy(true); setError(null);
    try {
      const out = await api.converse(model.value, prompt, { system, temperature: temp, maxTokens: Number(maxTok) || 256 });
      setTurns((t) => [...t, { q: prompt, out }]); setPrompt("");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <ContentLayout header={<Header variant="h1" info={<Link variant="info">Info</Link>}>Playground</Header>}>
      <CapabilityContainer id="bedrock.runtime" title="Playground">
        {!model ? (
          <Container><Box textAlign="center" padding="xxl"><SpaceBetween size="s">
            <Box variant="h2">Select a model to get started</Box><Box color="text-body-secondary">You can configure model parameters and generate content with AI.</Box>
            <ModelPicker options={opts} value={model} onChange={setModel} loading={models.loading} />
          </SpaceBetween></Box></Container>
        ) : (
          <Grid gridDefinition={[{ colspan: { default: 12, m: 9 } }, { colspan: { default: 12, m: 3 } }]}>
            <Container header={<Header variant="h2">{model.label}</Header>}>
              <SpaceBetween size="m">
                {turns.map((t, i) => (
                  <SpaceBetween key={i} size="xs">
                    <Box variant="awsui-key-label">You</Box><div style={{ whiteSpace: "pre-wrap" }}>{t.q}</div>
                    <Box variant="awsui-key-label">{model.label}</Box>
                    <div data-testid="converse-output" style={{ whiteSpace: "pre-wrap" }}>{t.out.output.message.content.map((c) => c.text).join("")}</div>
                    <Box variant="small" color="text-body-secondary">{t.out.usage.inputTokens} input tokens, {t.out.usage.outputTokens} output tokens, {t.out.metrics.latencyMs} ms, stop: {t.out.stopReason}</Box>
                  </SpaceBetween>))}
                {isImported && <ServingBar />}
                {error && <Alert type="error" header={error.code === "ModelNotReadyException" ? "The local model is not available" : error.code}>{error.message}</Alert>}
                <FormField label="Prompt"><Textarea value={prompt} rows={3} onChange={({ detail }) => setPrompt(detail.value)} ariaLabel="Prompt" placeholder="Write a prompt" /></FormField>
                <SpaceBetween direction="horizontal" size="xs"><Button variant="primary" loading={busy} disabled={!prompt} onClick={run}>Run</Button><Button onClick={() => { setTurns([]); setError(null); }}>Clear</Button></SpaceBetween>
              </SpaceBetween>
            </Container>
            <Container header={<Header variant="h2">Configurations</Header>}>
              <SpaceBetween size="m">
                <ModelPicker options={opts} value={model} onChange={setModel} loading={models.loading} />
                <FormField label="System prompt - optional"><Textarea value={system} rows={3} onChange={({ detail }) => setSystem(detail.value)} ariaLabel="System prompt" /></FormField>
                <FormField label="Temperature"><Slider value={temp} min={0} max={1} step={0.1} onChange={({ detail }) => setTemp(detail.value)} /></FormField>
                <FormField label="Maximum length"><Input type="number" value={maxTok} onChange={({ detail }) => setMaxTok(detail.value)} ariaLabel="Maximum length" /></FormField>
              </SpaceBetween>
            </Container>
          </Grid>)}
      </CapabilityContainer>
    </ContentLayout>
  );
}
