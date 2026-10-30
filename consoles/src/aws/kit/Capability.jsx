/* Capability disclaimers, driven by core/capabilities/aws/*.json (the same registry
 * tests/conformance/test_capabilities.py proves against the backend). Never hand-write a
 * disclaimer in a page — wrap the section in <CapabilityContainer id=…> instead.
 *
 *   full           → no badge
 *   limited        → "Limited in Vyomi" badge + popover with the limitations
 *   config_only    → "Config only" badge + popover; saves add "not enforced" to the notice
 *   not_simulated  → the whole section becomes the honest Not-simulated panel
 */
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Popover from "@cloudscape-design/components/popover";
import SpaceBetween from "@cloudscape-design/components/space-between";
import s3 from "../../../../core/capabilities/aws/s3.json";
import dynamodb from "../../../../core/capabilities/aws/dynamodb.json";
import sqs from "../../../../core/capabilities/aws/sqs.json";
import sns from "../../../../core/capabilities/aws/sns.json";
import { NotSimulatedContainer } from "./common.jsx";

const REGISTRY = { ...s3, ...dynamodb, ...sqs, ...sns };

export const SUBSTRATE = (typeof document !== "undefined" && document.querySelector('meta[name="vyomi-substrate"]')?.content) || "offline";

/** {title, level, limitations, api} for this substrate, or null if the id is unknown. */
export function capability(id) {
  const e = REGISTRY[id];
  if (!e) {
    if (typeof console !== "undefined") console.warn(`[vyomi] unknown capability id ${id}`);
    return null;
  }
  return { ...e, id, level: e.level?.[SUBSTRATE] || e.level?.offline || "not_simulated" };
}

const LABEL = { limited: "Limited in Vyomi", config_only: "Config only" };
const DEFAULT_NOTE = {
  limited: "This works in Vyomi with the limitations below.",
  config_only: "Vyomi stores this setting and returns it from the API exactly as configured, but does not enforce it.",
};

export function CapabilityBadge({ id }) {
  const c = capability(id);
  if (!c || c.level === "full" || c.level === "not_simulated") return null;
  return (
    <span data-vyomi-capability={c.level} data-vyomi-capability-id={id}>
      <Popover
        size="large"
        triggerType="custom"
        header={`${c.title}: ${LABEL[c.level]}`}
        content={
          <SpaceBetween size="xs">
            <Box variant="p">{DEFAULT_NOTE[c.level]}</Box>
            {c.limitations?.length > 0 && <ul style={{ margin: 0, paddingLeft: 18 }}>{c.limitations.map((l) => <li key={l}>{l}</li>)}</ul>}
            <Box variant="small" color="text-body-secondary">Applies to this Vyomi environment ({SUBSTRATE}).</Box>
          </SpaceBetween>
        }
      >
        <button type="button" aria-label={`${LABEL[c.level]} — details`} style={{ background: "none", border: 0, padding: 0, cursor: "pointer" }}>
          <Badge color={c.level === "limited" ? "blue" : "grey"}>{LABEL[c.level]}</Badge>
        </button>
      </Popover>
    </span>
  );
}

/** A console section whose header carries the capability badge; becomes the honest
 *  Not-simulated panel when the registry says so. */
export function CapabilityContainer({ id, title, description, actions, counter, children }) {
  const c = capability(id);
  if (!c || c.level === "not_simulated") {
    return <NotSimulatedContainer title={title} note={c?.limitations?.join(" ")} />;
  }
  return (
    <Container header={
      <Header variant="h2" counter={counter} description={description} actions={actions}>
        <SpaceBetween direction="horizontal" size="xs" alignItems="center">
          <span>{title}</span>
          <CapabilityBadge id={id} />
        </SpaceBetween>
      </Header>
    }>
      {children}
    </Container>
  );
}

/** Text to append to a save confirmation for a setting at this capability level. */
export function saveNotice(id) {
  const c = capability(id);
  if (c?.level === "config_only") return " Vyomi stores this setting but does not enforce it.";
  if (c?.level === "limited") return " Some behaviour is limited in Vyomi — see the badge for details.";
  return "";
}

/** Limitations for a set of capability ids — for the help panel's "Vyomi notes". */
export function notesFor(ids) {
  return ids.map(capability).filter((c) => c && c.level !== "full");
}
