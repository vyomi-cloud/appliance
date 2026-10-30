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
import { NotSimulated } from "../../kit/common.jsx";

function HonestList({ title, feature, note, columns, actions }) {
  return (
    <ContentLayout header={<Header variant="h1">{title}</Header>}>
      <Container header={<Header variant="h2" counter="(0)" actions={
        <SpaceBetween direction="horizontal" size="xs">
          {actions.map((a) => <Button key={a} disabled>{a}</Button>)}
        </SpaceBetween>
      }>{title}</Header>}>
        <SpaceBetween size="l">
          <NotSimulated feature={feature} note={note} />
          <Table variant="embedded" items={[]}
            columnDefinitions={columns.map((c) => ({ id: c, header: c, cell: () => "" }))}
            empty={<Box textAlign="center" color="inherit"><b>No data</b></Box>} />
        </SpaceBetween>
      </Container>
    </ContentLayout>
  );
}

function FieldStub({ label }) {
  return <FormField label={label}><Input value="" disabled placeholder="Not simulated in Vyomi" ariaLabel={label} /></FormField>;
}

function SectionStub({ title, fields = [] }) {
  return (
    <Container header={<Header variant="h3">{title}</Header>}>
      <SpaceBetween size="l">
        {fields.map((f) => <FieldStub key={f} label={f} />)}
      </SpaceBetween>
    </Container>
  );
}

// `steps`: array of {title, sections}. A falsy step `title` renders its sections directly
// (no extra wrapper) — used for single-page forms that aren't a wizard.
function HonestForm({ title, feature, note, steps }) {
  return (
    <ContentLayout header={<Header variant="h1">{title}</Header>}>
      <Container header={<Header variant="h2">{title}</Header>}>
        <SpaceBetween size="l">
          <NotSimulated feature={feature} note={note} />
          {steps.map((st, i) => (
            st.title ? (
              <Container key={st.title} header={<Header variant="h3">{st.title}</Header>}>
                <SpaceBetween size="l">
                  {(st.sections || []).map((s) => <SectionStub key={s.title} title={s.title} fields={s.fields} />)}
                </SpaceBetween>
              </Container>
            ) : (
              <SpaceBetween key={i} size="l">
                {(st.sections || []).map((s) => <SectionStub key={s.title} title={s.title} fields={s.fields} />)}
              </SpaceBetween>
            )
          ))}
        </SpaceBetween>
      </Container>
    </ContentLayout>
  );
}

export function ExportsToS3() {
  return <HonestList title="Exports to S3" feature="DynamoDB table exports to Amazon S3"
    note="Vyomi has no second account/bucket boundary to export a point-in-time or incremental table snapshot into."
    columns={["Export ARN", "Table name", "Destination S3 bucket", "Status", "Export job start time", "Export type"]}
    actions={["View details", "Export to S3"]} />;
}

export function ExportToS3() {
  return <HonestForm title="Export table to Amazon S3" feature="DynamoDB table exports to Amazon S3"
    note="Vyomi has no second account/bucket boundary to export a point-in-time or incremental table snapshot into."
    steps={[{ title: null, sections: [
      { title: "Export details", fields: ["Source table", "Destination S3 bucket", "S3 bucket owner"] },
      { title: "Filter table data - optional", fields: [] },
      { title: "Export settings", fields: ["Export type", "Export from a specific point in time"] },
      { title: "Additional settings", fields: ["Exported file format", "Encryption key type"] },
    ] }]} />;
}

export function ImportsFromS3() {
  return <HonestList title="Imports from S3" feature="DynamoDB table imports from Amazon S3"
    note="Vyomi has no second account/bucket boundary to import a table snapshot from."
    columns={["Import ID", "Table", "Format", "Status", "Import job start time", "End time"]}
    actions={["Import from S3"]} />;
}

export function ImportFromS3() {
  return <HonestForm title="Import from S3" feature="DynamoDB table imports from Amazon S3"
    note="Vyomi has no second account/bucket boundary to import a table snapshot from."
    steps={[
      { title: "Import options", sections: [{ title: "Import details", fields: ["Source S3 URL", "S3 bucket owner", "Import file compression", "Import file format"] }] },
      { title: "Destination table", sections: [{ title: "Table details", fields: ["Table name", "Partition key", "Sort key"] }] },
      { title: "Review and import", sections: [] },
    ]} />;
}
