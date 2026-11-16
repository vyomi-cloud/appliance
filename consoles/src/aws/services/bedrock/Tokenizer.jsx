/* Bedrock > Tokenizer: Model / Input / Token result (capture 010). Counts through the real CountTokens operation. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Alert from "@cloudscape-design/components/alert";
import Container from "@cloudscape-design/components/container";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";
import { modelOption, ModelPicker } from "./Common.jsx";

export default function Tokenizer() {
  const models = useAsync(() => api.listModels(), []);
  const [model, setModel] = useState(null);
  const [text, setText] = useState("");
  const [tokens, setTokens] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const opts = (models.data || []).filter((m) => m.outputModalities?.includes("TEXT")).map(modelOption);
  const count = async () => { setBusy(true); setError(null); try { setTokens(await api.countTokens(model.value, text)); } catch (e) { setError(e); setTokens(null); } finally { setBusy(false); } };
  return (
    <ContentLayout header={<Header variant="h1" info={<Link variant="info">Info</Link>} description="When you run inference with a foundation model, you're charged for the number of tokens in your input and output. With the tokenizer, you can estimate the number of tokens in your input and refine it as necessary to account for cost, as well as token quotas.">Tokenizer</Header>}>
      <SpaceBetween size="m">
        {error && <Alert type="error" header={error.code || "Error"}>{error.message}</Alert>}
        <ColumnLayout columns={3}>
          <Container header={<Header variant="h2" description={model ? undefined : "Select a model to begin generating a token count."}>Model</Header>}>
            <SpaceBetween size="s"><ModelPicker options={opts} value={model} onChange={setModel} loading={models.loading} /></SpaceBetween>
          </Container>
          <Container header={<Header variant="h2" description={<>Enter a prompt and choose <b>Count tokens</b>.</>} actions={<Button onClick={() => setText("Amazon Bedrock is a fully managed service that offers a choice of high-performing foundation models through a single API.")}>Insert sample text</Button>}>Input</Header>}>
            <SpaceBetween size="s">
              <Textarea value={text} rows={5} onChange={({ detail }) => { setText(detail.value); setTokens(null); }} ariaLabel="Input" />
              <Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button iconName="close" variant="icon" ariaLabel="Clear" onClick={() => { setText(""); setTokens(null); }} /><Button variant="primary" loading={busy} disabled={!model || !text} onClick={count}>Count tokens</Button></SpaceBetween></Box>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Token result</Header>}>
            <Box variant="awsui-key-label">Tokens</Box>
            <Box variant="h1" data-testid="token-count">{tokens === null ? "--" : tokens}</Box>
          </Container>
        </ColumnLayout>
      </SpaceBetween>
    </ContentLayout>
  );
}
