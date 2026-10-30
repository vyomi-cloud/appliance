/* Capability disclaimers, driven by core/capabilities/gcp/*.json (the same registry
 * tests/conformance/test_capabilities.py proves against the backend). Never hand-write a
 * disclaimer in a page — wrap the section in <CapabilityContainer id=…> instead.
 *
 *   full           → no badge
 *   limited        → "Limited in Vyomi" badge + popover with the limitations
 *   config_only    → "Config only" badge + popover; saves add "not enforced" to the notice
 *   not_simulated  → the whole section becomes the honest Not-simulated panel
 */
import { useState } from "react";
import { Box, Chip, IconButton, List, ListItem, Popover, Typography } from "@mui/material";
import monitoring from "../../../../core/capabilities/gcp/monitoring.json";
import { NotSimulatedContainer, Section } from "./common.jsx";
import { VyomiMark } from "../../common/VyomiMark.jsx";

const REGISTRY = { ...monitoring };

export const SUBSTRATE = (typeof document !== "undefined" && document.querySelector('meta[name="vyomi-substrate"]')?.content) || "offline";

/** {title, level, limitations} for this substrate, or null if the id is unknown. */
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
  const [anchor, setAnchor] = useState(null);
  const c = capability(id);
  if (!c || c.level === "full" || c.level === "not_simulated") return null;
  return (
    <span data-vyomi-capability={c.level} data-vyomi-capability-id={id}>
      <IconButton size="small" aria-label={`${LABEL[c.level]} — details`} onClick={(e) => setAnchor(e.currentTarget)} sx={{ p: 0, ml: 0.5 }}>
        <Chip size="small" clickable color={c.level === "limited" ? "info" : "default"} label={LABEL[c.level]} />
      </IconButton>
      <Popover open={!!anchor} anchorEl={anchor} onClose={() => setAnchor(null)} anchorOrigin={{ vertical: "bottom", horizontal: "left" }}>
        <Box sx={{ p: 2, maxWidth: 420 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>{c.title}: {LABEL[c.level]}</Typography>
          <Typography variant="body2">{DEFAULT_NOTE[c.level]}</Typography>
          {c.limitations?.length > 0 && (
            <List dense sx={{ listStyleType: "disc", pl: 2.5, py: 0 }}>
              {c.limitations.map((l) => <ListItem key={l} sx={{ display: "list-item", py: 0.25, px: 0 }}><Typography variant="body2">{l}</Typography></ListItem>)}
            </List>
          )}
          <Typography variant="caption" color="text.secondary">Applies to this <VyomiMark /> environment ({SUBSTRATE}).</Typography>
        </Box>
      </Popover>
    </span>
  );
}

/** A console section whose header carries the capability badge; becomes the honest
 *  Not-simulated panel when the registry says so. */
export function CapabilityContainer({ id, title, description, actions, children }) {
  const c = capability(id);
  if (!c || c.level === "not_simulated") {
    return <NotSimulatedContainer title={title} feature={c?.title || title} note={c?.limitations?.join(" ")} />;
  }
  return (
    <Section title={<>{title}<CapabilityBadge id={id} /></>} description={description} actions={actions}>
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
