/* Capability disclaimers, driven by core/capabilities/gcp/*.json (the same registry
 * tests/conformance/test_capabilities.py proves against the backend). Never hand-write a
 * disclaimer in a page — wrap the section in <CapabilityContainer id=…> instead.
 *
 *   full           → no badge
 *   limited        → "Limited in Vyomi" badge + popover with the limitations
 *   config_only    → "Config only" badge + popover; saves add "not enforced" to the notice
 *   not_simulated  → the whole section becomes the honest Not-simulated panel
 */
import { Chip, Popover, Stack, Typography } from "@mui/material";
import { useState } from "react";
import functions from "../../../../core/capabilities/gcp/functions.json";
import { NotSimulatedContainer, Section } from "./common.jsx";
import { VyomiMark } from "../../common/VyomiMark.jsx";

const REGISTRY = { ...functions };

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
  const [anchor, setAnchor] = useState(null);
  if (!c || c.level === "full" || c.level === "not_simulated") return null;
  return (
    <span data-vyomi-capability={c.level} data-vyomi-capability-id={id}>
      <Chip size="small" color={c.level === "limited" ? "info" : "default"} label={LABEL[c.level]}
        onClick={(e) => setAnchor(e.currentTarget)} sx={{ cursor: "pointer" }} />
      <Popover open={!!anchor} anchorEl={anchor} onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "left" }}>
        <Stack spacing={1} sx={{ p: 2, maxWidth: 360 }}>
          <Typography variant="subtitle2">{c.title}: {LABEL[c.level]}</Typography>
          <Typography variant="body2">{DEFAULT_NOTE[c.level]}</Typography>
          {c.limitations?.length > 0 && <ul style={{ margin: 0, paddingLeft: 18 }}>{c.limitations.map((l) => <li key={l}><Typography variant="body2">{l}</Typography></li>)}</ul>}
          <Typography variant="caption" color="text.secondary">Applies to this <VyomiMark /> environment ({SUBSTRATE}).</Typography>
        </Stack>
      </Popover>
    </span>
  );
}

/** A console section whose header carries the capability badge; becomes the honest
 *  Not-simulated panel when the registry says so. */
export function CapabilityContainer({ id, title, description, actions, children }) {
  const c = capability(id);
  if (!c || c.level === "not_simulated") {
    return <NotSimulatedContainer title={title} feature={c?.title} note={c?.limitations?.join(" ")} description={description} />;
  }
  return (
    <Section title={title} description={description} actions={<>{<CapabilityBadge id={id} />}{actions}</>}>
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
