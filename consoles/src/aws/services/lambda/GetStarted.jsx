/* Service landing page (first-run / Compute > AWS Lambda). The "Code sample" runner
 * invokes a real throwaway function over the native wire — Lambda's actual Invoke path,
 * not a canned response. */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import Textarea from "@cloudscape-design/components/textarea";
import Box from "@cloudscape-design/components/box";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import { follow } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const SAMPLES = {
  "Node.js": "exports.handler isn't run by Vyomi's sandbox (Python-only, see lambda.invoke) — try Python below.",
  Python: "def handler(event, context):\n    return {'message': 'Hello from Lambda!', 'event': event}\n",
};

export default function GetStarted() {
  const [lang, setLang] = useState({ value: "Python", label: "Python" });
  const [code, setCode] = useState(SAMPLES.Python);
  const [out, setOut] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true); setError(null); setOut(null);
    const name = `vyomi-sample-${Date.now().toString(36)}`;
    try {
      await api.createFunction({ FunctionName: name, Runtime: "python3.12", Code: { Source: code } });
      const r = await api.invoke(name, { source: "get-started sample" });
      setOut(JSON.stringify(r, null, 2));
    } catch (e) { setError(e); }
    finally { try { await api.deleteFunction(name); } catch { /* best-effort cleanup */ } setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1" actions={<Button variant="primary" href="#/lambda/create/function" onFollow={follow}>Create an Event Function</Button>}>AWS Lambda</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">How it works</Header>}>
          <SpaceBetween size="l">
            <Box variant="p">AWS Lambda runs your code in response to events without you managing servers. Pick a language sample, then Run it for real against Vyomi's Lambda sandbox.</Box>
            <FormField label="Code sample">
              <Select selectedOption={lang} onChange={({ detail }) => { setLang(detail.selectedOption); setCode(SAMPLES[detail.selectedOption.value] ?? ""); }}
                options={Object.keys(SAMPLES).map((v) => ({ value: v, label: v }))} />
            </FormField>
            <Textarea value={code} onChange={({ detail }) => setCode(detail.value)} rows={6} />
            <Button loading={busy} onClick={run}>Run</Button>
            {error && <ErrorAlert error={error} />}
            {out && <Box variant="code"><pre>{out}</pre></Box>}
          </SpaceBetween>
        </Container>

        <Container header={<Header variant="h2">Lambda offerings</Header>}>
          <SpaceBetween direction="horizontal" size="s">
            <Button variant="primary" href="#/lambda/create/function" onFollow={follow}>Create an Event Function</Button>
            <Button href="#/lambda/create/web-function" onFollow={follow}>Create a Web Function</Button>
            <Button href="#/lambda/create/microvm" onFollow={follow}>Start a microVM</Button>
          </SpaceBetween>
        </Container>

        <Container header={<Header variant="h2">Use cases</Header>}>
          <ColumnLayout columns={3} variant="text-grid">
            <Box>Real-time file processing</Box>
            <Box>API backends</Box>
            <Box>Event-driven data processing</Box>
          </ColumnLayout>
        </Container>

        <Container header={<Header variant="h2">Resources</Header>}>
          <SpaceBetween size="xs">
            <Button href="#/lambda/home" onFollow={follow} variant="link">Dashboard</Button>
            <Button href="#/lambda/extensions" onFollow={follow} variant="link">Extensions</Button>
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
