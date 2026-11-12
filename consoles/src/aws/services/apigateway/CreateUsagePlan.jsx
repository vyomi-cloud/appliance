import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Toggle from "@cloudscape-design/components/toggle";
import TagEditor from "@cloudscape-design/components/tag-editor";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const PERIODS = [{ value: "DAY", label: "Day" }, { value: "WEEK", label: "Week" }, { value: "MONTH", label: "Month" }];

export default function CreateUsagePlan() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [throttleOn, setThrottleOn] = useState(true);
  const [rate, setRate] = useState("1000");
  const [burst, setBurst] = useState("500");
  const [quotaOn, setQuotaOn] = useState(true);
  const [period, setPeriod] = useState(PERIODS[2]);
  const [requests, setRequests] = useState("10000");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const created = await api.createUsagePlan({
        name, description,
        throttle: throttleOn ? { rateLimit: Number(rate), burstLimit: Number(burst) } : undefined,
        quota: quotaOn ? { limit: Number(requests), period: period.value } : undefined,
        tags: Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value || ""])),
      });
      notify.success(`Usage plan "${created.name}" created.`);
      navigate("apigateway", "usage-plans");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create usage plan</Header>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} header="Couldn't create usage plan" />}
        <Container header={<Header variant="h2">Usage plan details</Header>}>
          <SpaceBetween size="l">
            <FormField label="Name" constraintText="Required"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
            <FormField label="Description - optional"><Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" /></FormField>
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2">Throttling</Header>}>
          <SpaceBetween size="l">
            <FormField label="Throttling"><Toggle checked={throttleOn} onChange={({ detail }) => setThrottleOn(detail.checked)}>Enable throttling</Toggle></FormField>
            {throttleOn && <SpaceBetween direction="horizontal" size="l">
              <FormField label="Rate"><Input type="number" value={rate} onChange={({ detail }) => setRate(detail.value)} ariaLabel="Rate" /></FormField>
              <FormField label="Burst"><Input type="number" value={burst} onChange={({ detail }) => setBurst(detail.value)} ariaLabel="Burst" /></FormField>
            </SpaceBetween>}
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2">Quota</Header>}>
          <SpaceBetween size="l">
            <FormField label="Quota"><Toggle checked={quotaOn} onChange={({ detail }) => setQuotaOn(detail.checked)}>Enable quota</Toggle></FormField>
            {quotaOn && <SpaceBetween direction="horizontal" size="l">
              <FormField label="Requests"><Input type="number" value={requests} onChange={({ detail }) => setRequests(detail.value)} ariaLabel="Requests" /></FormField>
              <FormField label="Requests per"><Select selectedOption={period} onChange={({ detail }) => setPeriod(detail.selectedOption)} options={PERIODS} /></FormField>
            </SpaceBetween>}
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2">Tags</Header>}>
          <FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} /></FormField>
        </Container>
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => navigate("apigateway", "usage-plans")}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!name} onClick={submit}>Create usage plan</Button>
          </SpaceBetween>
        </Box>
      </SpaceBetween>
    </ContentLayout>
  );
}
