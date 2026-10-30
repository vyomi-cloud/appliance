/* Service home — shown before the account has any topics, like the real console's
 * "homepage" (no side nav). A quick create-topic card that prefills the Create topic form. */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";

export default function Landing() {
  const [name, setName] = useState("");
  return (
    <ContentLayout header={<Header variant="h1">Amazon Simple Notification Service</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Create topic</Header>}>
          <SpaceBetween size="m">
            <Box>A topic is a logical access point and communication channel for sending notifications to subscribed endpoints.</Box>
            <FormField label="Topic name">
              <Input value={name} placeholder="MyTopic" onChange={({ detail }) => setName(detail.value)} ariaLabel="Topic name" />
            </FormField>
            <Button variant="primary" onClick={() => { location.hash = `/sns/create-topic${name ? `?name=${encodeURIComponent(name)}` : ""}`; }}>Next step</Button>
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
