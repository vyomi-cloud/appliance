/* Capability disclaimers, driven by core/capabilities/gcp/*.json (the same registry
 * tests/conformance/test_capabilities.py proves against the backend). Never hand-write a
 * disclaimer in a page — wrap the section in <CapabilityContainer id=…> instead. Mirrors
 * consoles/src/aws/kit/Capability.jsx for this lens.
 *
 *   full           → no badge
 *   limited        → "Limited in Vyomi" chip + note with the limitations
 *   config_only    → "Config only" chip + note; saves add "not enforced" to the notice
 *   not_simulated  → the whole section becomes the honest Not-simulated panel
 */
import { Chip, Stack, Tooltip } from "@mui/material";
import kubernetes from "../../../../core/capabilities/gcp/kubernetes.json";
import { NotSimulatedContainer, Section } from "./common.jsx";

const REGISTRY = { ...kubernetes };

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
  const note = [DEFAULT_NOTE[c.level], ...(c.limitations || [])].filter(Boolean).join(" ");
  return (
    <span data-vyomi-capability={c.level} data-vyomi-capability-id={id}>
      <Tooltip title={note} arrow>
        <Chip size="small" label={LABEL[c.level]} color={c.level === "limited" ? "info" : "default"} />
      </Tooltip>
    </span>
  );
}

/** A console section whose header carries the capability badge; becomes the honest
 *  Not-simulated panel when the registry says so. */
export function CapabilityContainer({ id, title, description, actions, children }) {
  const c = capability(id);
  if (!c || c.level === "not_simulated") {
    return <NotSimulatedContainer title={title} feature={c?.title || title} note={c?.limitations?.join(" ")} description={description} />;
  }
  return (
    <Section title={title} description={description} actions={<Stack direction="row" spacing={1} alignItems="center">{actions}<CapabilityBadge id={id} /></Stack>}>
      {children}
    </Section>
  );
}

/** Text to append to a save confirmation for a setting at this capability level. */
export function saveNotice(id) {
  const c = capability(id);
  if (c?.level === "config_only") return " Vyomi stores this setting but does not enforce it.";
  if (c?.level === "limited") return " Some behaviour is limited in Vyomi — see the badge for details.";
  return "";
}
