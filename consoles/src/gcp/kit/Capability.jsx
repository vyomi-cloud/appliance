/* Capability disclaimers, driven by core/capabilities/gcp/*.json (the same registry
 * tests/conformance/test_capabilities.py proves against the backend). Never hand-write a
 * disclaimer in a page — wrap the section in <CapabilityContainer id=…> instead. MUI analogue
 * of aws/kit/Capability.jsx.
 *
 *   full           → no badge
 *   limited        → "Limited in Vyomi" badge + popover with the limitations
 *   config_only    → "Config only" badge + popover; saves add "not enforced" to the notice
 *   not_simulated  → the whole section becomes the honest Not-simulated panel
 */
import { useState } from "react";
import { Box, Chip, IconButton, List, ListItem, ListItemText, Popover, Typography } from "@mui/material";
import compute from "../../../../core/capabilities/gcp/compute.json";
import { NotSimulatedContainer, Section } from "./common.jsx";
import { VyomiMark } from "../../common/VyomiMark.jsx";

const REGISTRY = { ...compute };

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
      <IconButton size="small" aria-label={`${LABEL[c.level]} — details`} onClick={(e) => setAnchor(e.currentTarget)}>
        <Chip size="small" color={c.level === "limited" ? "info" : "default"} label={LABEL[c.level]} />
      </IconButton>
      <Popover open={!!anchor} anchorEl={anchor} onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "left" }}>
        <Box sx={{ p: 2, maxWidth: 360 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>{c.title}: {LABEL[c.level]}</Typography>
          <Typography variant="body2" sx={{ mb: c.limitations?.length ? 1 : 0 }}>{DEFAULT_NOTE[c.level]}</Typography>
          {c.limitations?.length > 0 && (
            <List dense disablePadding>
              {c.limitations.map((l) => <ListItem key={l} disablePadding sx={{ display: "list-item", listStyleType: "disc", ml: 2 }}><ListItemText primaryTypographyProps={{ variant: "body2" }} primary={l} /></ListItem>)}
            </List>
          )}
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>Applies to this <VyomiMark /> environment ({SUBSTRATE}).</Typography>
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
    return <NotSimulatedContainer title={title} feature={c?.title || title} note={c?.limitations?.join(" ")} description={description} />;
  }
  return (
    <Section
      title={<Box sx={{ display: "inline-flex", alignItems: "center", gap: 1 }}>{title}<CapabilityBadge id={id} /></Box>}
      description={description} actions={actions}
    >
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
