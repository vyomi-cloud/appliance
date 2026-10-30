/* CloudFormation landing page ("Getting started") — pure navigation + static copy, like the
 * real console's home. Every link below routes to a page this service actually builds. */
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Container from "@cloudscape-design/components/container";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import Link from "@cloudscape-design/components/link";
import { follow, href } from "../../../common/router.js";

export default function Home() {
  return (
    <ContentLayout header={
      <Header variant="h1" actions={<Button variant="primary" href={href("cloudformation", "create")} onFollow={follow}>Create stack</Button>}>
        AWS CloudFormation
      </Header>
    }>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2" actions={<Button variant="primary" href={href("cloudformation", "create")} onFollow={follow}>Create stack</Button>}>Create a CloudFormation stack</Header>}>
          <Box variant="p">Use a template to model and provision the resources in your stack with Vyomi's CloudFormation engine.</Box>
        </Container>
        <Container header={<Header variant="h2">How it works</Header>}>
          <Box variant="p">CloudFormation reads a template that describes the resources you want, provisions them in dependency order, and tracks their status as a single stack you can update or delete as a unit.</Box>
        </Container>
        <Container header={<Header variant="h2">Benefits and features</Header>}>
          <SpaceBetween size="s">
            <Link href={href("cloudformation", "hooks", "overview")} onFollow={follow}>View Hooks overview</Link>
            <Link href={href("cloudformation", "template-studio")} onFollow={follow}>Build your template with template studio</Link>
            <Link href={href("cloudformation", "iac-generator")} onFollow={follow}>View IaC generator</Link>
            <Link href={href("cloudformation", "stacks")} onFollow={follow}>View stacks</Link>
            <Link href={href("cloudformation", "stacksets")} onFollow={follow}>View stack sets</Link>
            <Link href={href("cloudformation", "registry", "activated-extensions")} onFollow={follow}>View registry</Link>
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2">Getting started</Header>}>
          <Box variant="p">Start from a sample template in Template studio, or bring your own JSON/YAML template and create a stack.</Box>
        </Container>
        <Container header={<Header variant="h2">More resources</Header>}>
          <Box variant="p">See the Stacks page for every stack Vyomi has provisioned in this account and Region.</Box>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
