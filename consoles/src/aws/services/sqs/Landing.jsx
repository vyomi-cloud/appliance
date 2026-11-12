/* Service landing page — the real console's "Amazon SQS" marketing home. Purely
 * informational (no backend needed); Queues is the only item in the left nav. */
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import { navigate } from "../../../common/router.js";

const SECTIONS = [
  ["How it works", "Amazon SQS is a fully managed message queuing service. Vyomi backs CreateQueue, SendMessage, ReceiveMessage, DeleteMessage and visibility timeouts with a real, timestamp-accurate engine over the native AmazonSQS.* JSON wire — the same one an unmodified AWS SDK or CLI speaks."],
  ["Benefits and features", "Standard and FIFO queues, dead-letter queue redrive after a configurable maxReceiveCount, content-based and explicit message deduplication, per-group FIFO ordering, and real SNS-to-SQS fan-out when a topic is subscribed."],
  ["Related tools and services", "Subscribe this queue to an Amazon SNS topic from a queue's SNS subscriptions tab to receive its notifications as real, receivable messages."],
  ["Pricing", "Vyomi doesn't bill for SQS usage."],
  ["Getting started", "Create a queue to start sending and receiving messages."],
];

export default function Landing() {
  return (
    <ContentLayout header={<Header variant="h1" description="A message queuing service" actions={<Button variant="primary" onClick={() => navigate("sqs", "create-queue")}>Create queue</Button>}>Amazon SQS</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Get started</Header>}>
          <SpaceBetween size="s">
            <Box>Create a queue to decouple and scale your application components.</Box>
            <Button variant="primary" onClick={() => navigate("sqs", "create-queue")}>Create queue</Button>
          </SpaceBetween>
        </Container>
        {SECTIONS.map(([title, body]) => (
          <Container key={title} header={<Header variant="h2">{title}</Header>}><Box>{body}</Box></Container>
        ))}
      </SpaceBetween>
    </ContentLayout>
  );
}
