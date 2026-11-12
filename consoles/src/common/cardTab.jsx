/* "Dev Simplified" tab: a gray tab that sits inside the nearest bordered card, flush with its
 * bottom-right border. A capability badge renders a hidden marker, finds its card by walking up
 * the DOM (bordered + rounded + wide enough), and portals the tab into a slot on that card.
 * No card found → the caller falls back to its inline pill. Shared by the AWS/GCP/Azure consoles. */
import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const TAB_HEIGHT = 26;
const TAB_GAP = 14;

function isCard(n) {
  const cs = getComputedStyle(n);
  return parseFloat(cs.borderTopWidth) >= 1 && parseFloat(cs.borderBottomWidth) >= 1
    && parseFloat(cs.borderBottomRightRadius) >= 6 && n.offsetWidth > 240 && n.offsetHeight > 40;
}

/** The card enclosing the marker; else (badge sits in a header above its card) the next card
 *  that follows the marker within the nearest few ancestors. */
function findCard(start) {
  for (let n = start.parentElement; n && n !== document.body; n = n.parentElement) if (isCard(n)) return n;
  let scope = start.parentElement;
  for (let hop = 0; scope && scope !== document.body && hop < 4; hop += 1, scope = scope.parentElement) {
    for (const el of scope.querySelectorAll("*")) {
      if (!(start.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) || el.contains(start)) continue;
      if (el.closest("[data-vyomi-tab-slot]")) continue;
      if (isCard(el)) return el;
    }
  }
  return null;
}

/** [markerRef, slotElement|null] — put markerRef on a hidden span inside the card. */
export function useCardSlot(hostSelector) {
  const ref = useRef(null);
  const [slot, setSlot] = useState(null);
  useLayoutEffect(() => {
    const card = ref.current && (hostSelector ? ref.current.closest(hostSelector) : findCard(ref.current));
    if (!card) return undefined;
    const cs = getComputedStyle(card);
    let el = card.querySelector(":scope > [data-vyomi-tab-slot]");
    if (!el) {
      if (cs.position === "static") card.style.position = "relative";
      const clipped = cs.overflow !== "visible";
      const bw = clipped ? 0 : parseFloat(cs.borderBottomWidth);
      const rw = clipped ? 0 : parseFloat(cs.borderRightWidth);
      el = document.createElement("div");
      el.setAttribute("data-vyomi-tab-slot", "");
      // hostSelector = a page header: the tab sits on the divider under the title, at the far right (the divider bleeds 24px past the content)
      Object.assign(el.style, { position: "absolute", right: hostSelector ? "-24px" : `-${rw}px`, bottom: hostSelector ? "0px" : `-${bw}px`, display: "flex", gap: "4px", zIndex: "1" });
      el.dataset.radius = cs.borderBottomRightRadius;
      el.dataset.border = cs.borderBottomColor;
      el.dataset.clipped = clipped ? "1" : "";
      card.appendChild(el);
      if (!hostSelector) card.style.paddingBottom = `${parseFloat(cs.paddingBottom) + TAB_GAP}px`; // room so the tab never covers content
    }
    setSlot(el);
    return undefined;
  }, []);
  return [ref, slot];
}

function tabStyle(slot) {
  const clipped = slot.dataset.clipped === "1";
  const line = `1px solid ${slot.dataset.border || "#c6c6cd"}`;
  return {
    display: "inline-flex", alignItems: "center", height: TAB_HEIGHT, padding: "0 12px", boxSizing: "border-box",
    background: "#e9ebed", color: "#414d5c", fontSize: 12, lineHeight: "16px", whiteSpace: "nowrap",
    border: line, ...(clipped ? { borderRight: 0, borderBottom: 0 } : {}),
    borderRadius: `8px 0 ${slot.dataset.radius || "8px"} 0`,
  };
}

export const MarkerSpan = ({ markerRef }) => <span ref={markerRef} hidden data-vyomi-capability-marker="" />;

/** Portal the tab content into the card slot. `attrs` carries the data-vyomi-capability* attributes. */
export function CardTab({ slot, attrs, children }) {
  return createPortal(<span data-vyomi-capability-tab="" {...attrs} style={tabStyle(slot)}>{children}</span>, slot);
}
