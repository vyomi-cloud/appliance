/* Service landing page — no backend needed (static marketing copy + links into the
 * real pages), matching the native console's "no APIs yet" state. */
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import { navigate } from "../../../common/router.js";

export default function Welcome() {
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button variant="primary" onClick={() => navigate("apigateway", "create")}>Create an API</Button>}>API Gateway</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Get started</Header>}>
          <SpaceBetween size="s">
            <Box variant="p">Create, publish, maintain, monitor, and secure APIs at any scale.</Box>
            <Button variant="primary" onClick={() => navigate("apigateway", "create")}>Create an API</Button>
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2">API types</Header>}>
          <ColumnLayout columns={3} variant="text-grid">
            <div><Box variant="h4">REST API</Box><Box variant="p" color="text-body-secondary">Resources, methods and integrations with fine-grained control.</Box><Button onClick={() => navigate("apigateway", "create-rest-api")}>Create REST API</Button></div>
            <div><Box variant="h4">HTTP API</Box><Box variant="p" color="text-body-secondary">Low-latency, low-cost APIs for Lambda and HTTP backends.</Box><Button onClick={() => navigate("apigateway", "create-http-api")}>Create HTTP API</Button></div>
            <div><Box variant="h4">WebSocket API</Box><Box variant="p" color="text-body-secondary">Two-way communication between clients and your backend.</Box><Button onClick={() => navigate("apigateway", "create-websocket-api")}>Create WebSocket API</Button></div>
          </ColumnLayout>
        </Container>
        <Container header={<Header variant="h2">How it works</Header>}>
          <Box variant="p" color="text-body-secondary">A client calls your API's invoke URL; API Gateway routes the call to the resource/method's integration — a Lambda function, an HTTP backend, or a mock response — and returns the result.</Box>
        </Container>
        <Container header={<Header variant="h2">Pricing</Header>}>
          <Box variant="p" color="text-body-secondary">Vyomi simulates API Gateway for local development — there is no billing.</Box>
        </Container>
        <Container header={<Header variant="h2">Resources</Header>}>
          <Box variant="p" color="text-body-secondary">See the APIs page to manage existing APIs, or Usage plans and API keys to control access.</Box>
        </Container>
        <Container header={<Header variant="h2">Benefits</Header>}>
          <ColumnLayout columns={2} variant="text-grid">
            <div><Box variant="h4">Efficient API development</Box></div>
            <div><Box variant="h4">Performance at any scale</Box></div>
            <div><Box variant="h4">Cost savings</Box></div>
            <div><Box variant="h4">Easy monitoring</Box></div>
          </ColumnLayout>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
