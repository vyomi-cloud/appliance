/* Lambda dashboard "Set up your agent to build with Lambda": connect an agent to Lambda through an AgentCore MCP gateway
 * (real: creates the gateway, exposes the functions as tools) plus the endpoint config + prompt a coding agent needs. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { WIRE_BASE } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import * as api from "./api.js";

const GW = "lambda-tools";

export default function LambdaOnboarding() {
  const notify = useNotify();
  const gws = useAsync(() => api.listGateways(), []);
  const [model, setModel] = useState(null);
  const [busy, setBusy] = useState("");
  const gw = (gws.data || []).find((g) => g.name === GW);
  const origin = `${location.origin}${WIRE_BASE.replace(/\/_wire$/, "")}`;
  const prompt = `Use the AWS SDK/CLI against the Vyomi endpoint ${origin} (AWS_ENDPOINT_URL=${origin}, any credentials). ` +
    `Build and deploy Lambda functions there, then expose them as MCP tools through the AgentCore gateway "${GW}" (POST ${origin}/_wire/gateways/<gatewayId>/mcp).`;
  const check = async () => {
    setBusy("model");
    try { const r = await api.converse("amazon.nova-micro-v1:0", "ping", { maxTokens: 4 }); setModel({ ok: true, t: `${r.usage.outputTokens} tokens, ${r.metrics.latencyMs} ms` }); }
    catch (e) { setModel({ ok: false, t: e.message }); } finally { setBusy(""); }
  };
  const mk = async () => {
    setBusy("gw");
    try { const g = await api.createGateway(GW, "NONE", "MCP tools backed by Lambda functions"); notify.success("Gateway created."); gws.reload(); navigate("bedrock", "agentcore", "gateways", g.gatewayId); }
    catch (e) { notify.error(e); } finally { setBusy(""); }
  };
  return (
    <CapabilityContainer id="lambda.dashboard.agent-onboarding" title="Set up your agent to build with Lambda" description="Give an AI agent hands: expose Lambda functions as MCP tools through an AgentCore gateway.">
      <SpaceBetween size="m">
        <SpaceBetween size="xs">
          <Box variant="awsui-key-label">1. Local model</Box>
          <SpaceBetween direction="horizontal" size="xs"><Button loading={busy === "model"} onClick={check}>Check local model</Button>
            {model && (model.ok ? <StatusIndicator type="success">Model answered ({model.t})</StatusIndicator> : <StatusIndicator type="warning">{model.t}</StatusIndicator>)}</SpaceBetween>
        </SpaceBetween>
        <SpaceBetween size="xs">
          <Box variant="awsui-key-label">2. MCP gateway for Lambda</Box>
          {gw ? <StatusIndicator type="success">Gateway {GW} exists ({gw.status})</StatusIndicator> : <Button variant="primary" loading={busy === "gw"} onClick={mk}>Create gateway</Button>}
          {gw && <Button onClick={() => navigate("bedrock", "agentcore", "gateways", gw.gatewayId)}>Add Lambda targets</Button>}
        </SpaceBetween>
        <SpaceBetween size="xs">
          <Box variant="awsui-key-label">3. Agent prompt</Box>
          <Alert type="info"><span data-testid="agent-prompt">{prompt}</span></Alert>
          <Button iconName="copy" onClick={() => { try { navigator.clipboard.writeText(prompt); notify.success("Prompt copied."); } catch { notify.info("Select the text to copy it."); } }}>Copy prompt</Button>
        </SpaceBetween>
      </SpaceBetween>
    </CapabilityContainer>
  );
}
