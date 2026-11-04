/* Service landing page — purely informational (no backend needed), like the real
 * console's marketing page before any resources exist. */
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useState } from "react";
import { navigate } from "../../../common/router.js";

const RESOURCES = [
  { value: "bus", label: "EventBridge event bus", action: "Create event bus", go: () => navigate("eventbridge", "create-event-bus") },
  { value: "pipe", label: "EventBridge Pipe", action: "Create pipe", go: () => navigate("eventbridge", "create-pipe") },
  { value: "schedule", label: "EventBridge Schedule", action: "Create schedule", go: () => navigate("eventbridge", "create-schedule") },
  { value: "schema", label: "EventBridge Schema registry", action: "Create schema registry", go: () => navigate("eventbridge", "schemas") },
];

const SECTIONS = [
  ["How it works", "EventBridge routes events from a source to a target. Rules match events by pattern and fan them out to SQS queues, SNS topics or Lambda functions — all backed by real deliveries in Vyomi, not a log line."],
  ["Benefits and features", "Event buses, rules with pattern matching, archives and replay, and EventBridge Scheduler for one-time, rate- and cron-based schedules — over the same native AWSEvents / Scheduler wire a real AWS SDK or CLI speaks."],
  ["Use cases", "Decouple applications with event-driven architectures, fan events out to multiple targets, schedule recurring jobs without managing a cron server."],
  ["Pricing", "Vyomi doesn't bill for EventBridge usage."],
  ["More resources", "See Custom event buses, Rules, Archives and Scheduler in the left navigation."],
];

export default function Home() {
  const [resource, setResource] = useState("bus");
  const current = RESOURCES.find((r) => r.value === resource);
  return (
    <ContentLayout header={<Header variant="h1" description="Serverless event bus for application integration">Amazon EventBridge</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Get started</Header>}>
          <SpaceBetween size="s">
            <Box variant="p">Choose a resource to create.</Box>
            <RadioGroup value={resource} onChange={({ detail }) => setResource(detail.value)}
              items={RESOURCES.map((r) => ({ value: r.value, label: r.label }))} ariaLabel="Resource to create" />
            <Button variant="primary" onClick={current.go}>{current.action}</Button>
          </SpaceBetween>
        </Container>
        {SECTIONS.map(([title, body]) => (
          <Container key={title} header={<Header variant="h2">{title}</Header>}><Box variant="p">{body}</Box></Container>
        ))}
      </SpaceBetween>
    </ContentLayout>
  );
}
