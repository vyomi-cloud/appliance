/* Capability disclaimers, driven by core/capabilities/azure/*.json (the same registry
 * tests/conformance/test_capabilities.py proves against the backend). Never hand-write a
 * disclaimer in a page — wrap the section in <CapabilityContainer id=…> instead.
 *
 *   full           → no badge
 *   limited        → "Limited in Vyomi" badge + popover with the limitations
 *   config_only    → "Config only" badge + popover; saves add "not enforced" to the notice
 *   not_simulated  → the whole section becomes the honest Not-simulated panel
 */
import { Badge, Popover, PopoverSurface, PopoverTrigger } from "@fluentui/react-components";
import { NotSimulatedContainer } from "./common.jsx";
import cap_acr from "../../../../core/capabilities/azure/acr.json";
import cap_aks from "../../../../core/capabilities/azure/aks.json";
import cap_apim from "../../../../core/capabilities/azure/apim.json";
import cap_appservices from "../../../../core/capabilities/azure/appservices.json";
import cap_cost from "../../../../core/capabilities/azure/cost.json";
import cap_eventgrid from "../../../../core/capabilities/azure/eventgrid.json";
import cap_functionapp from "../../../../core/capabilities/azure/functionapp.json";
import cap_keyvaults from "../../../../core/capabilities/azure/keyvaults.json";
import cap_monitor from "../../../../core/capabilities/azure/monitor.json";
import cap_nsgs from "../../../../core/capabilities/azure/nsgs.json";
import cap_resourcegroups from "../../../../core/capabilities/azure/resourcegroups.json";
import cap_servicebus from "../../../../core/capabilities/azure/servicebus.json";
import cap_sql from "../../../../core/capabilities/azure/sql.json";

const REGISTRY = { ...cap_acr, ...cap_aks, ...cap_apim, ...cap_appservices, ...cap_cost, ...cap_eventgrid, ...cap_functionapp, ...cap_keyvaults, ...cap_monitor, ...cap_nsgs, ...cap_resourcegroups, ...cap_servicebus, ...cap_sql };

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
      <Popover withArrow>
        <PopoverTrigger disableButtonEnhancement>
          <button type="button" aria-label={`${LABEL[c.level]} — details`} style={{ background: "none", border: 0, padding: 0, cursor: "pointer" }}>
            <Badge color={c.level === "limited" ? "brand" : "informative"} appearance="tint">{LABEL[c.level]}</Badge>
          </button>
        </PopoverTrigger>
        <PopoverSurface style={{ maxWidth: 320 }}>
          <b>{c.title}: {LABEL[c.level]}</b>
          <p style={{ margin: "6px 0" }}>{DEFAULT_NOTE[c.level]}</p>
          {c.limitations?.length > 0 && <ul style={{ margin: 0, paddingLeft: 18 }}>{c.limitations.map((l) => <li key={l}>{l}</li>)}</ul>}
          <div style={{ marginTop: 6, fontSize: 12, opacity: 0.75 }}>Applies to this Vyomi environment ({SUBSTRATE}).</div>
        </PopoverSurface>
      </Popover>
    </span>
  );
}

/** A console section whose header carries the capability badge; becomes the honest
 *  Not-simulated panel when the registry says so. */
export function CapabilityContainer({ id, title, actions, children }) {
  const c = capability(id);
  if (!c || c.level === "not_simulated") {
    return <NotSimulatedContainer title={title} note={c?.limitations?.join(" ")} />;
  }
  return (
    <section className="vy-form-section">
      <h3 style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span>{title}</span>
        <CapabilityBadge id={id} />
        {actions && <span style={{ marginLeft: "auto" }}>{actions}</span>}
      </h3>
      {children}
    </section>
  );
}

/** Text to append to a save confirmation for a setting at this capability level. */
export function saveNotice(id) {
  const c = capability(id);
  if (c?.level === "config_only") return " Vyomi stores this setting but does not enforce it.";
  if (c?.level === "limited") return " Some behaviour is limited in Vyomi — see the badge for details.";
  return "";
}
