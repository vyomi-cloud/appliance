/* Capability disclaimers for the GCP lens, driven by core/capabilities/gcp/*.json (the same
 * registry tests/conformance/test_capabilities.py proves against the backend). Never
 * hand-write a disclaimer in a page — wrap the section in <CapabilityContainer id=…> instead.
 *
 *   full           → no badge
 *   limited        → "Limited in Vyomi" badge + popover with the limitations
 *   config_only    → "Config only" badge + popover; saves add "not enforced" to the notice
 *   not_simulated  → the whole section becomes the honest Not-simulated panel
 */
import { CardTab, MarkerSpan, useCardSlot } from "../../common/cardTab.jsx";
import { useState } from "react";
import { Box, Chip, Popover, Stack, Typography } from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/esm/InfoOutlined.js";
import { NotSimulatedContainer, Section } from "./common.jsx";
import cap_artifacts from "../../../../core/capabilities/gcp/artifacts.json";
import cap_backupdr from "../../../../core/capabilities/gcp/backupdr.json";
import cap_clouddeploy from "../../../../core/capabilities/gcp/clouddeploy.json";
import cap_cloudbuild from "../../../../core/capabilities/gcp/cloudbuild.json";
import cap_securitycenter from "../../../../core/capabilities/gcp/securitycenter.json";
import cap_cloudscheduler from "../../../../core/capabilities/gcp/cloudscheduler.json";
import cap_compute from "../../../../core/capabilities/gcp/compute.json";
import cap_eventarc from "../../../../core/capabilities/gcp/eventarc.json";
import cap_firestore from "../../../../core/capabilities/gcp/firestore.json";
import cap_functions from "../../../../core/capabilities/gcp/functions.json";
import cap_iam_admin from "../../../../core/capabilities/gcp/iam-admin.json";
import cap_kms from "../../../../core/capabilities/gcp/kms.json";
import cap_kubernetes from "../../../../core/capabilities/gcp/kubernetes.json";
import cap_logs from "../../../../core/capabilities/gcp/logs.json";
import cap_memorystore from "../../../../core/capabilities/gcp/memorystore.json";
import cap_monitoring from "../../../../core/capabilities/gcp/monitoring.json";
import cap_networking from "../../../../core/capabilities/gcp/networking.json";
import cap_pubsub from "../../../../core/capabilities/gcp/pubsub.json";
import cap_resource_manager from "../../../../core/capabilities/gcp/resource-manager.json";
import cap_run from "../../../../core/capabilities/gcp/run.json";
import cap_secret_manager from "../../../../core/capabilities/gcp/secret-manager.json";
import cap_sql from "../../../../core/capabilities/gcp/sql.json";
import cap_vertex_ai from "../../../../core/capabilities/gcp/vertex-ai.json";
import cap_storage from "../../../../core/capabilities/gcp/storage.json";

const REGISTRY = { ...cap_artifacts, ...cap_cloudscheduler, ...cap_compute, ...cap_firestore, ...cap_functions, ...cap_iam_admin, ...cap_kms, ...cap_kubernetes, ...cap_logs, ...cap_memorystore, ...cap_monitoring, ...cap_networking, ...cap_pubsub, ...cap_resource_manager, ...cap_run, ...cap_secret_manager, ...cap_sql, ...cap_storage, ...cap_vertex_ai, ...cap_eventarc, ...cap_clouddeploy, ...cap_backupdr, ...cap_cloudbuild, ...cap_securitycenter };

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

export function CapabilityBadge({ id, host }) {
  const [anchor, setAnchor] = useState(null);
  const [markerRef, slot] = useCardSlot(host);
  const c = capability(id);
  if (!c || c.level === "full" || c.level === "not_simulated") return null;
  const attrs = { "data-vyomi-capability": c.level, "data-vyomi-capability-id": id };
  const popover = (
    <Popover open={!!anchor} anchorEl={anchor} onClose={() => setAnchor(null)}
      anchorOrigin={{ vertical: "top", horizontal: "left" }} transformOrigin={{ vertical: "bottom", horizontal: "left" }}>
      <Box sx={{ p: 2, maxWidth: 360 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>{c.title}: {LABEL[c.level]}</Typography>
        <Stack spacing={1}>
          <Typography variant="body2">{DEFAULT_NOTE[c.level]}</Typography>
          {c.limitations?.length > 0 && (
            <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
              {c.limitations.map((l) => <li key={l}><Typography variant="body2">{l}</Typography></li>)}
            </Box>
          )}
          <Typography variant="caption" color="text.secondary">Applies to this Vyomi environment ({SUBSTRATE}).</Typography>
        </Stack>
      </Box>
    </Popover>
  );
  return (
    <>
      <MarkerSpan markerRef={markerRef} />
      {slot ? (
        <CardTab slot={slot} attrs={attrs}>
          <button type="button" aria-label={`${LABEL[c.level]} — details`} onClick={(e) => setAnchor(e.currentTarget)}
            style={{ background: "none", border: 0, padding: 0, cursor: "pointer", font: "inherit", color: "inherit" }}>{LABEL[c.level]}</button>
          {popover}
        </CardTab>
      ) : (
        <span {...attrs}>
          <Chip size="small" color={c.level === "limited" ? "info" : "default"} label={LABEL[c.level]}
            onClick={(e) => setAnchor(e.currentTarget)} icon={<InfoOutlinedIcon fontSize="small" />} />
          {popover}
        </span>
      )}
    </>
  );
}

/** A console section; its capability tab attaches to the bottom-right border. Becomes the
 *  honest Not-simulated panel when the registry says so. */
export function CapabilityContainer({ id, title, description, actions, children }) {
  const c = capability(id);
  if (!c || c.level === "not_simulated") {
    return <NotSimulatedContainer title={title} note={c?.limitations?.join(" ")} />;
  }
  return (
    <Section title={title} description={description} actions={actions}>
      {children}
      <CapabilityBadge id={id} />
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
