/* Vyomi brand for every console's top bar: the Vyomi mark + "vyomi" + the cloud name, e.g.
 * "vyomi | AWS". Inline SVG (works offline/Nano). Only Vyomi's own mark is drawn — never a
 * cloud vendor's logo; the cloud is named in plain text. */

const esc = (s) => String(s).replace(/[<>&"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c]));

/** Approximate text width (px) for layout of the SVG at the given font size. */
// Capitals and wide letters take more room than lowercase; over-estimate rather than clip.
const textWidth = (s, size, bold) => Math.ceil([...s].reduce((w, ch) =>
  w + size * (/[A-Z]|[mw]/.test(ch) ? 0.74 : ch === " " ? 0.3 : 0.56) * (bold ? 1.06 : 1), 0));

/**
 * @param {string} cloud  cloud name shown after the divider ("AWS", "Google Cloud", "Azure")
 * @param {{text?: string, sub?: string, divider?: string}} colors  per top bar
 * @returns {{src: string, width: number, height: number}}
 */
export function wordmark(cloud, { text = "#ffffff", sub = "#d1d5db", divider = "rgba(255,255,255,0.35)" } = {}) {
  const word = "vyomi", h = 32;
  const xWord = 36, wWord = textWidth(word, 20, true);
  const xDiv = xWord + wWord + 10, xCloud = xDiv + 11, wCloud = textWidth(cloud, 17, false);
  const w = xCloud + wCloud + 4;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">` +
    `<rect x="0" y="2" width="28" height="28" rx="6" fill="#2f6fde"/>` +
    `<path d="M7 11l7 11 7-11" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>` +
    `<text x="${xWord}" y="23" font-family="Helvetica Neue, Arial, sans-serif" font-size="20" font-weight="700" fill="${text}">${word}</text>` +
    `<rect x="${xDiv}" y="8" width="1.5" height="17" fill="${divider}"/>` +
    `<text x="${xCloud}" y="22.5" font-family="Helvetica Neue, Arial, sans-serif" font-size="17" font-weight="400" fill="${sub}">${esc(cloud)}</text>` +
    `</svg>`;
  return { src: "data:image/svg+xml;utf8," + encodeURIComponent(svg), width: w, height: h };
}
