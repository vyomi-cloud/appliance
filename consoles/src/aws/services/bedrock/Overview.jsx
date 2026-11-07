import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { navigate } from "../../../common/router.js";
import * as api from "./api.js";
import { NOVA } from "./Common.jsx";

export default function Overview() {
  const [st, setSt] = useState(null);
  const [busy, setBusy] = useState(false);
  const [webllm, setWebllm] = useState(null);
  const canWebLLM = typeof window !== "undefined" && typeof window.vyomiEnableWebLLM === "function";   // only the Nano page provides the bridge
  const enable = async () => {
    setWebllm({ msg: "Loading the in-browser model..." });
    try { const id = await window.vyomiEnableWebLLM(undefined, (p) => setWebllm({ msg: p.text || "Loading..." })); setWebllm({ ok: true, msg: `WebLLM model ${id} is registered as the local model.` }); }
    catch (e) { setWebllm({ ok: false, msg: String(e.message || e) }); }
  };
  const check = async () => {
    setBusy(true);
    try { const r = await api.converse(NOVA, "ping", { maxTokens: 4 }); setSt({ ok: true, backend: `${r.usage.outputTokens} tokens in ${r.metrics.latencyMs} ms` }); }
    catch (e) { setSt({ ok: false, msg: e.message }); } finally { setBusy(false); }
  };
  return (
    <ContentLayout header={<Header variant="h1" description="Build generative AI applications with foundation models, knowledge bases and agents - on a model that runs locally.">Amazon Bedrock</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2" actions={<Button loading={busy} onClick={check}>Check local model</Button>}>Local model</Header>}>
          <SpaceBetween size="s">
            <Box>The pool lists ten open models. Without a booster only the small local model (Qwen2.5 3B: llama.cpp on the appliance, WebLLM in the browser on Nano when it is available) answers; the other nine need the booster (Pro/Max). Quality is toy-grade; use it to exercise prompts, RAG, agents and token accounting.</Box>
            {canWebLLM && <SpaceBetween direction="horizontal" size="xs"><Button onClick={enable}>Enable in-browser model (WebLLM)</Button>
              {webllm && (webllm.ok === false ? <StatusIndicator type="warning">{webllm.msg}</StatusIndicator> : <StatusIndicator type={webllm.ok ? "success" : "in-progress"}>{webllm.msg}</StatusIndicator>)}</SpaceBetween>}
            {st?.ok && <StatusIndicator type="success">Model answered ({st.backend})</StatusIndicator>}
            {st && !st.ok && <Alert type="warning" header="No local model is running">{st.msg}</Alert>}
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2">Get started</Header>}>
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => navigate("bedrock", "playground")}>Open the playground</Button>
            <Button onClick={() => navigate("bedrock", "knowledge-bases")}>Knowledge bases</Button>
            <Button onClick={() => navigate("bedrock", "agents")}>Agents</Button>
            <Button onClick={() => navigate("bedrock", "agentcore", "gateways")}>AgentCore gateways</Button>
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
