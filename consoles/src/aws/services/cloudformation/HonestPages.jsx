/* Declared gaps: Hooks, the public-extensions registry + publisher workflow, and
 * Spotlight editorial content are out of Vyomi's scope (core/capabilities/aws/
 * cloudformation.json: aws.cloudformation.hooks, .registry.public-extensions-publisher,
 * .spotlight). These render the REAL page shape (title, tabs, columns, sections, fields)
 * so every element a user would look for is visibly and specifically declared "Not
 * simulated in Vyomi" — not just a generic placeholder — per consoles/AGENT-UI.md. */
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { NotSimulatedContainer } from "../../kit/common.jsx";

function GapPage({ title, children }) {
  return <ContentLayout header={<Header variant="h1">{title}</Header>}><SpaceBetween size="l">{children}</SpaceBetween></ContentLayout>;
}

export function HooksOverview() {
  return (
    <GapPage title="Hooks overview">
      <NotSimulatedContainer title="Get started" feature="CloudFormation Hooks" />
      <NotSimulatedContainer title="Use cases" />
      <NotSimulatedContainer title="Benefits and features" />
    </GapPage>
  );
}

export function InvocationSummary() {
  return (
    <GapPage title="Invocation summary">
      <NotSimulatedContainer title="Invocation summary" feature="CloudFormation Hooks"
        note="Columns: Invocation ID, Target, Mode, Invocation time, Result message. Actions: Create a Hook. Empty state: No Hook invocations in this Region." />
    </GapPage>
  );
}

export function Hooks() {
  return (
    <GapPage title="Hooks">
      <NotSimulatedContainer title="Hooks" feature="CloudFormation Hooks"
        note="Columns: Name, Type, Mode, Targets, Hook status, Last updated, Description. Actions: Delete, Create a Hook." />
      <NotSimulatedContainer title="How it works" />
    </GapPage>
  );
}

export function PublicExtensions() {
  return (
    <GapPage title="Registry: Public extensions">
      <NotSimulatedContainer title="Registry: Public extensions" feature="Public extensions registry"
        note="Columns: Type name, Publisher, Description, Last updated. Actions: Activate." />
      <NotSimulatedContainer title="Filter" note="Extension type: Resource types, Modules, Hooks. Publisher: AWS, Third party." />
    </GapPage>
  );
}

export function ExtensionDetail({ params }) {
  const name = params.name || "AWS::S3::Bucket";
  return (
    <ContentLayout header={<Header variant="h1">{name}</Header>}>
      <SpaceBetween size="l">
        <NotSimulatedContainer title="Overview" feature="Public extensions registry" note="ARN, Publisher, Description, Release date, Visibility." />
        <Tabs tabs={[
          { id: "schema", label: "Schema", content: <NotSimulatedContainer title="Schema" /> },
          { id: "configuration", label: "Configuration", content: <NotSimulatedContainer title="Configuration" /> },
        ]} />
      </SpaceBetween>
    </ContentLayout>
  );
}

export function Publisher() {
  return (
    <GapPage title="Registry: Publisher">
      <NotSimulatedContainer title="Publisher registration" feature="Publisher registration" note="Status: This account is not registered as a publisher." />
    </GapPage>
  );
}

export function Spotlight() {
  return (
    <GapPage title="CloudFormation Spotlight">
      <NotSimulatedContainer title="Filters" feature="CloudFormation Spotlight"
        note="Filter by: All tags. Sort by: Sort by newest. Show editor's choice only. Show bookmarks only." />
    </GapPage>
  );
}
