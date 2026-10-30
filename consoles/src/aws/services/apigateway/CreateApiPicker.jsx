/* Create API — choose an API type, then Build opens the type-specific create page.
 * (OpenAPI/AsyncAPI Import isn't modeled by Vyomi; only Build is offered.) */
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { navigate } from "../../../common/router.js";

const CARDS = [
  { key: "create-http-api", label: "HTTP API", help: "Works with: Lambda, HTTP backends" },
  { key: "create-websocket-api", label: "WebSocket API", help: "Works with: Lambda, HTTP, AWS Services" },
  { key: "create-rest-api", label: "REST API", help: "Works with: Lambda, HTTP, AWS Services" },
  { key: "create-rest-api-private", label: "REST API Private", help: "Create a REST API that is only accessible from within a VPC.", route: "create-rest-api" },
];

export default function CreateApiPicker() {
  return (
    <ContentLayout header={<Header variant="h1">Create API</Header>}>
      <Container header={<Header variant="h2">Choose an API type</Header>}>
        <ColumnLayout columns={4} variant="text-grid">
          {CARDS.map((c) => (
            <SpaceBetween key={c.key} size="s">
              <Box variant="h3">{c.label}</Box>
              <Box variant="p" color="text-body-secondary">{c.help}</Box>
              <Button onClick={() => navigate("apigateway", c.route || c.key)}>Build</Button>
            </SpaceBetween>
          ))}
        </ColumnLayout>
      </Container>
    </ContentLayout>
  );
}
