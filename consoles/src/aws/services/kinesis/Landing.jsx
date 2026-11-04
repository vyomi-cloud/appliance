/* Service landing page — shown before the account has any data streams. */
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import { navigate } from "../../../common/router.js";

const SECTIONS = [
  ["How it works", "Amazon Kinesis Data Streams captures, stores and replays a continuous stream of records across shards, so many producers and consumers can process the same data independently."],
  ["Benefits and features", "Vyomi backs stream creation, shards (split, merge, scale), the data viewer (put/get records), retention, server-side encryption, resource policies, tags and enhanced fan-out consumers against the same Kinesis_20131202 wire a real AWS SDK or CLI speaks."],
  ["Pricing", "Vyomi doesn't bill for Kinesis usage."],
  ["Getting started", "Create a data stream, choose a capacity mode, and start putting and getting records."],
];

export default function Landing() {
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button variant="primary" onClick={() => navigate("kinesis", "streams", "create")}>Create data stream</Button>}>Amazon Kinesis</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Get started now</Header>}>
          <SpaceBetween size="s">
            <Box>Create a data stream to start capturing and processing records in real time.</Box>
            <Button variant="primary" onClick={() => navigate("kinesis", "streams", "create")}>Create data stream</Button>
          </SpaceBetween>
        </Container>
        {SECTIONS.map(([title, body]) => (
          <Container key={title} header={<Header variant="h2">{title}</Header>}><Box>{body}</Box></Container>
        ))}
      </SpaceBetween>
    </ContentLayout>
  );
}
