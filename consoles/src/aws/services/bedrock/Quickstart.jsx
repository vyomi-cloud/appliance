/* Bedrock > Quickstart: "Choose your use case" tiles (capture 004), each with the real runtime API samples. */
import { useState } from "react";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tabs from "@cloudscape-design/components/tabs";
import Tiles from "@cloudscape-design/components/tiles";
import { WIRE_BASE } from "../../../common/wire.js";
import { navigate } from "../../../common/router.js";
import { NOVA } from "./Common.jsx";

const CASES = [
  { id: "text", name: "Generate text", desc: "Create text from prompts and instructions", apis: ["Responses", "Converse", "Invoke"] },
  { id: "stream", name: "Stream responses", desc: "Receive model output in real-time", apis: ["Responses", "Converse", "Invoke"] },
  { id: "media", name: "Analyze media", desc: "Understand and extract information from documents, images, videos", apis: ["Converse", "Invoke"] },
];
const ep = () => String(WIRE_BASE || "").replace(/\/_wire$/, "") || "http://localhost:4566";
const snippet = (use, api) => {
  const c = `import boto3\n\nbr = boto3.client("bedrock-runtime", region_name="us-east-1", endpoint_url="${ep()}/_wire")\n`;
  if (api === "Converse") {
    if (use === "stream") return `${c}r = br.converse_stream(modelId="${NOVA}", messages=[{"role": "user", "content": [{"text": "Write a haiku about clouds."}]}])\nfor e in r["stream"]:\n    if "contentBlockDelta" in e:\n        print(e["contentBlockDelta"]["delta"]["text"], end="")`;
    if (use === "media") return `${c}doc = open("report.pdf", "rb").read()\nr = br.converse(modelId="${NOVA}", messages=[{"role": "user", "content": [{"document": {"format": "pdf", "name": "report", "source": {"bytes": doc}}}, {"text": "Summarize this document."}]}])\nprint(r["output"]["message"]["content"][0]["text"])`;
    return `${c}r = br.converse(modelId="${NOVA}", messages=[{"role": "user", "content": [{"text": "Write a haiku about clouds."}]}])\nprint(r["output"]["message"]["content"][0]["text"])`;
  }
  if (api === "Invoke") return `${c}import json\nbody = json.dumps({"messages": [{"role": "user", "content": [{"text": "Write a haiku about clouds."}]}]})\n${use === "stream" ? 'r = br.invoke_model_with_response_stream(modelId="' + NOVA + '", body=body)\nfor e in r["body"]:\n    print(e["chunk"]["bytes"].decode())' : 'r = br.invoke_model(modelId="' + NOVA + '", body=body)\nprint(json.loads(r["body"].read()))'}`;
  return "# The OpenAI-compatible Responses endpoint is not simulated here; use the Converse or Invoke tab (same models, same wire).";
};

export default function Quickstart() {
  const [use, setUse] = useState(null);
  const [api, setApi] = useState("Converse");
  const sel = CASES.find((c) => c.id === use);
  return (
    <ContentLayout header={<Header variant="h1" description="Make your first API call to Amazon Bedrock in minutes.">Quickstart</Header>}>
      <SpaceBetween size="l">
        <SpaceBetween size="s">
          <Header variant="h2">Choose your use case</Header>
          <Tiles value={use} onChange={({ detail }) => setUse(detail.value)} columns={3} items={CASES.map((c) => ({ value: c.id, label: c.name, description: <SpaceBetween size="s"><span>{c.desc}</span><SpaceBetween direction="horizontal" size="xxs">{c.apis.map((a) => <Badge key={a} color="blue">{a}</Badge>)}</SpaceBetween></SpaceBetween> }))} />
        </SpaceBetween>
        {sel && (
          <Container header={<Header variant="h2" actions={<Button onClick={() => navigate("bedrock", "playground")}>Open in playground</Button>}>{sel.name}</Header>}>
            <Tabs activeTabId={sel.apis.includes(api) ? api : "Converse"} onChange={({ detail }) => setApi(detail.activeTabId)} tabs={sel.apis.map((a) => ({ id: a, label: a, content: <pre data-testid="quickstart-code" style={{ whiteSpace: "pre-wrap", margin: 0, fontSize: 13 }}>{snippet(sel.id, a)}</pre> }))} />
            <Box margin={{ top: "s" }} color="text-body-secondary" variant="small">Samples target this simulator's bedrock-runtime endpoint; swap endpoint_url for the real one when you deploy.</Box>
          </Container>
        )}
      </SpaceBetween>
    </ContentLayout>
  );
}
