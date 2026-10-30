/* Declared gaps for the S3 import/export surface (`may_stay_not_simulated` — Vyomi has no
 * second cloud account/bucket boundary to export into or import from). These render the
 * REAL page shape (columns, actions, sections, fields) so every element a user would look
 * for is visibly and specifically declared "Not simulated in Vyomi" — not just a generic
 * placeholder panel — per consoles/AGENT-UI.md's honesty rule. */
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Container from "@cloudscape-design/components/container";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Box from "@cloudscape-design/components/box";
import { NotSimulated, NotSimulatedContainer } from "../../kit/common.jsx";

// A feature Vyomi does not back renders ONLY its title and an honest note — never a
// disabled skeleton of the real page (that would be static UI posing as a feature).
function HonestList({ title, feature, note }) {
  return <ContentLayout header={<Header variant="h1">{title}</Header>}><NotSimulatedContainer title={title} feature={feature} note={note} /></ContentLayout>;
}

function HonestForm({ title, feature, note }) {
  return <ContentLayout header={<Header variant="h1">{title}</Header>}><NotSimulatedContainer title={title} feature={feature} note={note} /></ContentLayout>;
}

export function ExportsToS3() {
  return <HonestList title="Exports to S3" feature="DynamoDB table exports to Amazon S3"
    note="Export into the simulator's own S3 store is planned (config-integration plan, wave W3)."
    columns={["Export ARN", "Table name", "Destination S3 bucket", "Status", "Export job start time", "Export type"]}
    actions={["View details", "Export to S3"]} />;
}

export function ExportToS3() {
  return <HonestForm title="Export table to Amazon S3" feature="DynamoDB table exports to Amazon S3"
    note="Export into the simulator's own S3 store is planned (config-integration plan, wave W3)."
    steps={[{ title: null, sections: [
      { title: "Export details", fields: ["Source table", "Destination S3 bucket", "S3 bucket owner"] },
      { title: "Filter table data - optional", fields: [] },
      { title: "Export settings", fields: ["Export type", "Export from a specific point in time"] },
      { title: "Additional settings", fields: ["Exported file format", "Encryption key type"] },
    ] }]} />;
}

export function ImportsFromS3() {
  return <HonestList title="Imports from S3" feature="DynamoDB table imports from Amazon S3"
    note="Import from the simulator's own S3 store is planned (config-integration plan, wave W3)."
    columns={["Import ID", "Table", "Format", "Status", "Import job start time", "End time"]}
    actions={["Import from S3"]} />;
}

export function ImportFromS3() {
  return <HonestForm title="Import from S3" feature="DynamoDB table imports from Amazon S3"
    note="Import from the simulator's own S3 store is planned (config-integration plan, wave W3)."
    steps={[
      { title: "Import options", sections: [{ title: "Import details", fields: ["Source S3 URL", "S3 bucket owner", "Import file compression", "Import file format"] }] },
      { title: "Destination table", sections: [{ title: "Table details", fields: ["Table name", "Partition key", "Sort key"] }] },
      { title: "Review and import", sections: [] },
    ]} />;
}
