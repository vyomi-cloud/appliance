/* Declared gaps: the public-extensions registry + publisher workflow, and Spotlight
 * editorial content are out of Vyomi's scope (core/capabilities/aws/cloudformation.json:
 * .registry.public-extensions-publisher, .spotlight). Hooks overview/invocation
 * summary/hooks list are real now — see HooksOverview.jsx, InvocationSummary.jsx,
 * Hooks.jsx. These render the REAL page shape (title, tabs, columns, sections, fields)
 * so every element a user would look for is visibly and specifically declared "Not
 * simulated in Vyomi" — not just a generic placeholder — per consoles/AGENT-UI.md. */
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { NotSimulatedContainer } from "../../kit/common.jsx";

function GapPage({ title, children }) {
  return <ContentLayout header={<Header variant="h1">{title}</Header>}><SpaceBetween size="l">{children}</SpaceBetween></ContentLayout>;
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
