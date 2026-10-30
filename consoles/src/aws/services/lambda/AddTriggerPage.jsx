/* Add trigger — creates an event-source-mapping-shaped trigger record for ANY of the
 * console's source types (see core/lambda_core.py module docstring + lambda.triggers
 * capability: real CRUD, but no cross-service polling/subscription). */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import Input from "@cloudscape-design/components/input";
import Checkbox from "@cloudscape-design/components/checkbox";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { follow, href } from "../../../common/router.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const SOURCES = ["API Gateway", "EventBridge (CloudWatch Events)", "S3", "SNS", "SQS", "DynamoDB", "Kinesis", "CloudWatch Logs"];

export default function AddTriggerPage({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [source, setSource] = useState(null);
  const [arn, setArn] = useState("");
  const [active, setActive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!source) return;
    setBusy(true); setError(null);
    try {
      await api.createEventSourceMapping({
        FunctionName: name, EventSourceArn: arn || `arn:aws:${source.value.split(" ")[0].toLowerCase()}:us-east-1:123456789012:resource`,
        EventSourceType: source.value, Enabled: active,
      });
      notify.success(`Trigger added to "${name}".`);
      location.hash = `${href("lambda", "functions", name).slice(1)}?tab=configuration`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Add trigger</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href={`#/lambda/functions/${encodeURIComponent(name)}?tab=configuration`} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Add</Button>
          </SpaceBetween>}
          errorText={error && <ErrorAlert error={error} />}
        >
          <Container header={<Header variant="h2">Trigger configuration</Header>}>
            <SpaceBetween size="l">
              <FormField label="Select a source">
                <Select selectedOption={source} onChange={({ detail }) => setSource(detail.selectedOption)}
                  options={SOURCES.map((v) => ({ value: v, label: v }))} placeholder="Choose a source" />
              </FormField>
              {source && (
                <FormField label="Source ARN - optional" description="Leave blank to use a generated placeholder ARN.">
                  <Input value={arn} onChange={({ detail }) => setArn(detail.value)} ariaLabel="Source ARN" />
                </FormField>
              )}
              <Checkbox checked={active} onChange={({ detail }) => setActive(detail.checked)}>Activate trigger</Checkbox>
            </SpaceBetween>
          </Container>
        </Form>
      </form>
    </ContentLayout>
  );
}
