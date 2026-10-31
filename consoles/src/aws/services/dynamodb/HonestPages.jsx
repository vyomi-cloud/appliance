/* Declared gaps for the S3 import surface (`may_stay_not_simulated` — see
 * core/capabilities/aws/dynamodb.json's "dynamodb.imports" entry for the concrete reason:
 * parsing arbitrary external CSV/DynamoDB-JSON/Ion S3 content is out of scope; exports
 * (Exports.jsx/ExportToS3.jsx) ARE built this wave). These render the REAL page shape
 * (columns, actions, sections, fields) so every element a user would look for is visibly
 * and specifically declared "Not simulated in Vyomi" — not just a generic placeholder
 * panel — per consoles/AGENT-UI.md's honesty rule. */
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { capability } from "../../kit/Capability.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";

function gapNote(id, note) {
  const c = capability(id);
  return [c?.limitations?.join(" "), note].filter(Boolean).join(" ");
}

// A feature Vyomi does not back renders ONLY its title and an honest note — never a
// disabled skeleton of the real page (that would be static UI posing as a feature).
function HonestList({ title, feature, note }) {
  return <ContentLayout header={<Header variant="h1">{title}</Header>}><NotSimulatedContainer title={title} feature={feature} note={note} /></ContentLayout>;
}

function HonestForm({ title, feature, note }) {
  return <ContentLayout header={<Header variant="h1">{title}</Header>}><NotSimulatedContainer title={title} feature={feature} note={note} /></ContentLayout>;
}

export function ImportsFromS3() {
  return <HonestList title="Imports from S3" feature="DynamoDB table imports from Amazon S3"
    note={gapNote("dynamodb.imports", "Columns: Import ID, Table, Format, Status, Import job start time, End time. Action: Import from S3.")} />;
}

export function ImportFromS3() {
  return <HonestForm title="Import from S3" feature="DynamoDB table imports from Amazon S3"
    note={gapNote("dynamodb.imports", "Steps: Import options (Source S3 URL, S3 bucket owner, Import file compression, Import file format), "
      + "Destination table (Table name, Partition key, Sort key), Review and import.")} />;
}
