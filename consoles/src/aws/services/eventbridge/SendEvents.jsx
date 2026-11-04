import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Textarea from "@cloudscape-design/components/textarea";
import { ErrorAlert } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

export default function SendEvents({ params }) {
  const bus = params?.name || "default";
  const { data: buses = [] } = useAsync(() => api.listEventBuses());
  const [source, setSource] = useState("my.app");
  const [detailType, setDetailType] = useState("Event");
  const [detail, setDetail] = useState('{\n  "key": "value"\n}');
  const [resources, setResources] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      JSON.parse(detail || "{}");
      const r = await api.putEvents([{
        EventBusName: bus, Source: source, DetailType: detailType, Detail: detail || "{}",
        Resources: resources.split(",").map((s) => s.trim()).filter(Boolean),
      }]);
      setResult(r);
    } catch (e) { setError(e instanceof SyntaxError ? new Error("Event detail must be valid JSON.") : e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Send events</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button href={href("eventbridge", "event-buses", bus)} onFollow={follow}>Close</Button>
          <Button variant="primary" loading={busy} onClick={submit}>Send</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          {result && (
            <Alert type={result.FailedEntryCount ? "error" : "success"} header={result.FailedEntryCount ? "Failed to send" : "Event sent"}>
              {result.FailedEntryCount
                ? (result.Entries[0]?.ErrorMessage || "The event could not be delivered.")
                : `Event ID ${result.Entries[0]?.EventId} was matched against every ENABLED rule on ${bus} and delivered to any matching targets.`}
            </Alert>
          )}
          <Container header={<Header variant="h2">Event entry 1</Header>}>
            <SpaceBetween size="l">
              <FormField label="Event bus">
                <Select selectedOption={{ value: bus, label: bus }} onChange={() => {}} disabled
                  options={buses.map((b) => ({ value: b.Name, label: b.Name }))} ariaLabel="Event bus" />
              </FormField>
              <FormField label="Event source"><Input value={source} onChange={({ detail }) => setSource(detail.value)} ariaLabel="Event source" /></FormField>
              <FormField label="Detail type"><Input value={detailType} onChange={({ detail }) => setDetailType(detail.value)} ariaLabel="Detail type" /></FormField>
              <FormField label="Event detail" stretch><Textarea value={detail} onChange={({ detail: d }) => setDetail(d.value)} rows={8} ariaLabel="Event detail" /></FormField>
              <ExpandableSection headerText="Additional options">
                <FormField label="Resources" description="Comma-separated list of ARNs this event concerns (optional).">
                  <Input value={resources} onChange={({ detail }) => setResources(detail.value)} ariaLabel="Resources" />
                </FormField>
              </ExpandableSection>
            </SpaceBetween>
          </Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}
