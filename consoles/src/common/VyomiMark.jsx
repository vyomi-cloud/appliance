/* The Vyomi logo (static/brand/vyomi-text.png) used in place of the word "Vyomi" in page
 * text. Drawn as a mask filled with currentColor, so it takes the colour of the text around
 * it — body copy, alerts, badges, links, light and dark mode. Screen readers read "Vyomi".
 * Plain-text-only places (tab titles, aria-labels, placeholders, code) keep the word. */
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
