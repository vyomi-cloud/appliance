/* Bedrock playground: Converse against the local model through the real Bedrock Runtime wire. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Textarea from "@cloudscape-design/components/textarea";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";
import { modelOption } from "./Common.jsx";

export default function Playground() {
  const models = useAsync(() => api.listModels(), []);
  const [model, setModel] = useState(null);
  const [system, setSystem] = useState("");
  const [prompt, setPrompt] = useState("Say hello in five words.");
  const [out, setOut] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const opts = (models.data || []).filter((m) => m.outputModalities?.includes("TEXT")).map(modelOption);
  const sel = model || opts[0];
  const run = async () => {
    setBusy(true); setError(null); setOut(null);
    try { setOut(await api.converse(sel.value, prompt, { system })); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <ContentLayout header={<Header variant="h1" description="Send a Converse request to a model in the Vyomi pool.">Chat / text playground</Header>}>
      <CapabilityContainer id="bedrock.runtime" title="Playground">
        <SpaceBetween size="m">
          <FormField label="Model" description="Choose one of the ten pool models. Without a booster only the local small model answers; the others need the booster (Pro/Max)."><Select selectedOption={sel || null} onChange={({ detail }) => setModel(detail.selectedOption)} options={opts} statusType={models.loading ? "loading" : "finished"} ariaLabel="Model" /></FormField>
          <FormField label="System prompt - optional"><Textarea value={system} rows={2} onChange={({ detail }) => setSystem(detail.value)} ariaLabel="System prompt" /></FormField>
          <FormField label="Prompt"><Textarea value={prompt} rows={4} onChange={({ detail }) => setPrompt(detail.value)} ariaLabel="Prompt" /></FormField>
          <Box><Button variant="primary" loading={busy} disabled={!sel || !prompt} onClick={run}>Run</Button></Box>
          {error && <Alert type="error" header={error.code === "ModelNotReadyException" ? "The local model is not available" : error.code}>{error.message}</Alert>}
          {out && (
            <SpaceBetween size="s">
              <Box variant="awsui-key-label">Response</Box>
              <Box data-testid="converse-output"><div style={{ whiteSpace: "pre-wrap" }}>{out.output.message.content.map((c) => c.text).join("")}</div></Box>
              <ColumnLayout columns={4} variant="text-grid">
                <div><Box variant="awsui-key-label">Input tokens</Box>{out.usage.inputTokens}</div>
                <div><Box variant="awsui-key-label">Output tokens</Box>{out.usage.outputTokens}</div>
                <div><Box variant="awsui-key-label">Stop reason</Box>{out.stopReason}</div>
                <div><Box variant="awsui-key-label">Latency</Box>{out.metrics.latencyMs} ms</div>
              </ColumnLayout>
            </SpaceBetween>)}
        </SpaceBetween>
      </CapabilityContainer>
    </ContentLayout>
  );
}
