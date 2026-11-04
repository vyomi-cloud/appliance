/* Declared gap: Spotlight editorial content is out of Vyomi's scope (core/capabilities/aws/cloudformation.json:
 * .spotlight). The public-extensions registry + publisher workflow are real now (Registry.jsx). Hooks overview/invocation
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

export function Spotlight() {
  return (
    <GapPage title="CloudFormation Spotlight">
      <NotSimulatedContainer title="Filters" feature="CloudFormation Spotlight"
        note="Filter by: All tags. Sort by: Sort by newest. Show editor's choice only. Show bookmarks only." />
    </GapPage>
  );
}
