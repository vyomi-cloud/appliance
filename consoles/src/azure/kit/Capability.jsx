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
import eventgrid from "../../../../core/capabilities/azure/eventgrid.json";
import { NotSimulatedContainer } from "./common.jsx";
import { VyomiMark } from "../../common/VyomiMark.jsx";

const REGISTRY = { ...eventgrid };

export const SUBSTRATE = (typeof document !== "undefined" && document.querySelector('meta[name="vyomi-substrate"]')?.content) || "offline";

/** {title, level, limitations, tests} for this substrate, or null if the id is unknown. */
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
      <Popover withArrow size="large">
        <PopoverTrigger disableButtonEnhancement>
          <button type="button" aria-label={`${LABEL[c.level]} — details`} style={{ background: "none", border: 0, padding: 0, cursor: "pointer" }}>
            <Badge color={c.level === "limited" ? "important" : "subtle"} appearance="tint">{LABEL[c.level]}</Badge>
          </button>
        </PopoverTrigger>
        <PopoverSurface>
          <div style={{ maxWidth: 360, display: "flex", flexDirection: "column", gap: 6 }}>
            <b>{c.title}: {LABEL[c.level]}</b>
            <span>{DEFAULT_NOTE[c.level]}</span>
            {c.limitations?.length > 0 && <ul style={{ margin: 0, paddingLeft: 18 }}>{c.limitations.map((l) => <li key={l}>{l}</li>)}</ul>}
            <span style={{ fontSize: 12, color: "var(--colorNeutralForeground3)" }}>Applies to this <VyomiMark /> environment ({SUBSTRATE}).</span>
          </div>
        </PopoverSurface>
      </Popover>
    </span>
  );
}

/** A console section whose title row carries the capability badge; becomes the honest
 *  Not-simulated panel when the registry says so. `note` adds context (e.g. which menu
 *  items this gap covers) alongside the registry's own limitations — never a substitute
 *  for them. */
export function CapabilityContainer({ id, title, note, children }) {
  const c = capability(id);
  if (!c || c.level === "not_simulated") {
    return <NotSimulatedContainer title={title} note={[...(c?.limitations || []), note].filter(Boolean).join(" ")} />;
  }
  return (
    <section className="vy-section">
      {title && <h3 style={{ display: "flex", alignItems: "center", gap: 8 }}><span>{title}</span><CapabilityBadge id={id} /></h3>}
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
