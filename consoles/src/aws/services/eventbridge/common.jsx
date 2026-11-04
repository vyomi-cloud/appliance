/* Shared bits for the EventBridge service only (not the cross-service kit). */
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tabs from "@cloudscape-design/components/tabs";
import spec from "../../../../../ui-spec/aws/eventbridge.json";

const page = (id) => spec.pages.find((p) => p.id === id);

function fieldLabels(fields, acc) {
  for (const f of fields || []) {
    if (f.label && f.type !== "readonly") acc.push(f.label);
    fieldLabels(f.children, acc);
  }
}

function sectionLines(sections) {
  return (sections || []).map((s) => {
    const labels = [];
    fieldLabels(s.fields, labels);
    return s.title + (labels.length ? ": " + labels.join(", ") : "");
  });
}

/** Every checkable element (columns, actions, sections, fields, steps) this spec page
 * carries, outside its title/tabs (which the caller renders for real). Used so a page
 * Vyomi genuinely doesn't back still discloses each specific item by name — never a
 * generic "not simulated" with no detail, and never a disabled skeleton of the real UI. */
function gapLines(p) {
  const lines = [];
  const t = p.table;
  if (t) {
    if (t.columns?.length) lines.push("Columns — " + t.columns.map((c) => (typeof c === "string" ? c : c.label || c.header)).join(", "));
    const actions = (t.header_actions || []).filter((a) => !/^refresh$/i.test(a));
    if (actions.length) lines.push("Actions — " + actions.join(", "));
    if (t.filter_placeholder) lines.push(`Search — "${t.filter_placeholder}"`);
  }
  lines.push(...sectionLines(p.sections));
  for (const st of p.steps || []) {
    lines.push("Step — " + st.title);
    lines.push(...sectionLines(st.sections));
  }
  for (const panel of p.tab_panels || []) lines.push(...sectionLines(panel.sections));
  return lines;
}

function GapBox({ title, lines, note }) {
  return (
    <div data-vyomi-gap-box="">
      <Box padding="l" textAlign="center" color="text-body-secondary" data-vyomi-not-simulated={title}>
        <SpaceBetween size="xs">
          <Badge color="grey">Not simulated in Vyomi</Badge>
          <Box variant="p" color="inherit">{title} isn't backed by a Vyomi backend yet.</Box>
          {lines.map((l) => <Box key={l} variant="small" color="inherit">{l}</Box>)}
          {note && <Box variant="small" color="inherit">{note}</Box>}
        </SpaceBetween>
      </Box>
    </div>
  );
}

/** Minimal i18nStrings for <Wizard> (Cloudscape requires every string explicitly). */
export const WIZARD_I18N = {
  stepNumberLabel: (n) => `Step ${n}`,
  collapsedStepsLabel: (n, total) => `Step ${n} of ${total}`,
  navigationAriaLabel: "Steps",
  cancelButton: "Cancel",
  previousButton: "Previous",
  nextButton: "Next",
  submitButton: "Submit",
  optional: "optional",
};

/** A whole ancillary page (Pipes, Schemas, Connections, ...) this run doesn't build a
 * backend for. The title and tabs are real, clickable navigation; everything each tab
 * would show is honestly declared, by name, in a single gap panel per tab. */
export default function GapPage({ pageId, note }) {
  const p = page(pageId);
  const lines = gapLines(p);
  return (
    <ContentLayout header={<Header variant="h1">{p.title}</Header>}>
      {p.tabs?.length ? (
        <Tabs tabs={p.tabs.map((label) => ({ id: label, label, content: <GapBox title={p.title} lines={lines} note={note} /> }))} />
      ) : (
        <GapBox title={p.title} lines={lines} note={note} />
      )}
    </ContentLayout>
  );
}
