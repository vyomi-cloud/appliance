/* Vyomi brand for every console's top bar. Inline (works offline/Nano). Only Vyomi's own
 * logo is drawn — never a cloud vendor's logo; the cloud is named in plain text. */
import { WORDMARK_DARK, WORDMARK_H, WORDMARK_LIGHT, WORDMARK_W } from "./brand-assets.js";

const esc = (s) => String(s).replace(/[<>&"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c]));

/** Approximate text width (px) for layout of the SVG at the given font size. */
// Capitals and wide letters take more room than lowercase; over-estimate rather than clip.
const textWidth = (s, size, bold) => Math.ceil([...s].reduce((w, ch) =>
  w + size * (/[A-Z]|[mw]/.test(ch) ? 0.74 : ch === " " ? 0.3 : 0.56) * (bold ? 1.06 : 1), 0));

/**
 * Top-bar brand: the official Vyomi wordmark (the same artwork the portal shows — see
 * tools/brand/make_console_brand.py) + a divider + the cloud name, e.g. "vyomi.cloud | AWS".
 * @param {string} cloud  "AWS", "Google Cloud", "Azure"
 * @param {{bar?: "dark"|"light", sub?: string, divider?: string}} opts  bar = top-bar background
 * @returns {{src: string, width: number, height: number}}
 */
export function wordmark(cloud, { bar = "dark", sub, divider } = {}) {
  const h = 32;
  const wm = { w: Math.round(WORDMARK_W * h / WORDMARK_H), src: bar === "dark" ? WORDMARK_DARK : WORDMARK_LIGHT };
  const subColor = sub || (bar === "dark" ? "#e5e7eb" : "#3c4043");
  const divColor = divider || (bar === "dark" ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.25)");
  const xDiv = wm.w + 10, xCloud = xDiv + 11, wCloud = textWidth(cloud, 17, false);
  const w = xCloud + wCloud + 4;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">` +
    `<image x="0" y="0" width="${wm.w}" height="${h}" href="${wm.src}" xlink:href="${wm.src}"/>` +
    `<rect x="${xDiv}" y="8" width="1.5" height="17" fill="${divColor}"/>` +
    `<text x="${xCloud}" y="22" font-family="Helvetica Neue, Arial, sans-serif" font-size="17" font-weight="400" fill="${subColor}">${esc(cloud)}</text>` +
    `</svg>`;
  return { src: "data:image/svg+xml;utf8," + encodeURIComponent(svg), width: w, height: h };
}
