/* The Vyomi logo (static/brand/vyomi-text.png) inline in a line of text. Used ONLY for the
 * landing page's welcome line — everywhere else "Vyomi" stays plain text in the page font.
 * Drawn as a mask filled with currentColor so it matches the text colour (light and dark);
 * screen readers read "Vyomi". */
import { Fragment } from "react";
import { WORDMARK_H, WORDMARK_LIGHT, WORDMARK_W } from "./brand-assets.js";

// The trimmed artwork spans the descender of "y" to the dot of "i"; at 1.2em its x-height
// lines up with the surrounding text.
const H = 1.2;
const STYLE = {
  display: "inline-block", height: `${H}em`, width: `${(H * WORDMARK_W) / WORDMARK_H}em`, verticalAlign: "-0.3em",
  backgroundColor: "currentColor", margin: "0 0.08em",
  WebkitMask: `url("${WORDMARK_LIGHT}") center / contain no-repeat`, mask: `url("${WORDMARK_LIGHT}") center / contain no-repeat`,
};

export function VyomiMark() {
  return <span role="img" aria-label="Vyomi" style={STYLE} />;
}

/** A string with every "Vyomi" swapped for the logo (unchanged if it has none). */
export function vy(text) {
  if (typeof text !== "string" || !text.includes("Vyomi")) return text;
  const parts = text.split(/\bVyomi\b/);
  return parts.map((p, i) => <Fragment key={i}>{p}{i < parts.length - 1 && <VyomiMark />}</Fragment>);
}
