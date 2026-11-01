/* Grid + divider chrome checks, run in the page at any console view (used by ui-conformance.mjs's
 * GRID_AUDIT mode and grid-audit.mjs). Findings:
 *  no_rounded_border       a table outside any rounded card
 *  lines_not_edge_to_edge  a table narrower than its card (row lines stop short)
 *  tabs_no_divider         a MUI tab strip with no line under it
 *  tabs_not_edge_to_edge   a page-level tab strip short of the content card's edges
 *  divider_not_edge        a page-level horizontal rule short of the content card's edges
 *  divider_inset_in_card   a horizontal rule inside a card short of that card's edges */
import { appendFileSync } from "node:fs";

function probe() {
  const out = [];
  const visible = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== "hidden"; };
  const hasEdge = (e, pseudo) => {
    const c = getComputedStyle(e, pseudo);
    return (parseFloat(c.borderTopWidth) > 0 && c.borderTopStyle !== "none" && parseFloat(c.borderLeftWidth) > 0) || (c.boxShadow && c.boxShadow !== "none");
  };
  const cardOf = (t) => {
    for (let a = t.parentElement; a && a !== document.body; a = a.parentElement) {
      if (parseFloat(getComputedStyle(a).borderTopLeftRadius) >= 4 && (hasEdge(a) || hasEdge(a, "::before") || hasEdge(a, "::after"))) return a;
    }
    return null;
  };
  for (const t of document.querySelectorAll("table")) {
    if (!visible(t)) continue;
    const card = cardOf(t), tr = t.getBoundingClientRect();
    let head = "";
    for (let a = t; a && !head; a = a.parentElement) { const h = a.querySelector && a.querySelector("h1,h2,h3"); if (h) head = h.textContent.trim().slice(0, 60); }
    const cols = [...t.querySelectorAll("thead th")].slice(0, 4).map((c) => c.textContent.trim().slice(0, 24)).join("|");
    if (!card) { out.push({ issue: "no_rounded_border", head, cols, width: Math.round(tr.width) }); continue; }
    const cr = card.getBoundingClientRect(), cs = getComputedStyle(card);
    const scroller = t.parentElement && t.parentElement.scrollWidth > t.parentElement.clientWidth + 1;
    const l = Math.round(tr.left - cr.left - parseFloat(cs.borderLeftWidth)), rt = Math.round(cr.right - tr.right - parseFloat(cs.borderRightWidth));
    if (!scroller && (l > 1 || rt > 1)) out.push({ issue: "lines_not_edge_to_edge", head, cols, left: l, right: rt });
  }
  const main = document.querySelector("main");
  if (!main || !document.querySelector("[class*=Mui]")) return out;      // the checks below are the MUI (GCP) lens
  const m = main.getBoundingClientRect();
  for (const t of document.querySelectorAll(".MuiTabs-root")) {
    if (!visible(t)) continue;
    const tabs = [...t.querySelectorAll("[role=tab]")].slice(0, 3).map((x) => x.textContent.trim().slice(0, 16)).join("|");
    const line = (e) => parseFloat(getComputedStyle(e).borderBottomWidth) > 0;
    if (!line(t) && !line(t.parentElement)) { out.push({ issue: "tabs_no_divider", cols: tabs }); continue; }
    if (t.closest(".MuiPaper-root")) continue;
    const box = line(t) ? t : t.parentElement, r = box.getBoundingClientRect();
    if (r.left - m.left > 1 || m.right - r.right > 1) out.push({ issue: "tabs_not_edge_to_edge", cols: tabs, left: Math.round(r.left - m.left), right: Math.round(m.right - r.right) });
  }
  // Rules: <hr>/MuiDivider, plus any element drawing a lone top or bottom border (a hand-made rule).
  const seen = new Set();
  for (const e of main.querySelectorAll("hr, .MuiDivider-root, div, section, header, footer, form, ul, li")) {
    if (!visible(e) || e.closest("table, .MuiTabs-root, [role=tablist], [role=dialog], [role=menu], [role=listbox], .MuiTabs-root, .MuiInputBase-root, button, a")) continue;
    const c = getComputedStyle(e), r = e.getBoundingClientRect();
    const isRule = e.matches("hr, .MuiDivider-root");
    if (isRule && r.width < r.height) continue;      // a vertical divider
    const top = parseFloat(c.borderTopWidth) > 0 && c.borderTopStyle !== "none", bot = parseFloat(c.borderBottomWidth) > 0 && c.borderBottomStyle !== "none";
    const side = parseFloat(c.borderLeftWidth) > 0 || parseFloat(c.borderRightWidth) > 0;
    if (!(isRule || ((top !== bot) && !side)) || r.width < 200) continue;
    const paper = e.closest(".MuiPaper-root");
    const box = paper ? paper.getBoundingClientRect() : m;
    const bl = paper ? parseFloat(getComputedStyle(paper).borderLeftWidth) : 0, br = paper ? parseFloat(getComputedStyle(paper).borderRightWidth) : 0;
    const l = Math.round(r.left - box.left - bl), rt = Math.round(box.right - r.right - br);
    if (l > 1 || rt > 1) {
      let head = "";
      for (let a = e; a && !head; a = a.parentElement) { const h = a.querySelector && a.querySelector("h1,h2,h3"); if (h) head = h.textContent.trim().slice(0, 40); }
      const k = `${l}/${rt}/${head}`;
      if (seen.has(k)) continue; seen.add(k);
      out.push({ issue: paper ? "divider_inset_in_card" : "divider_not_edge", head, cols: isRule ? "hr" : (e.className || "").toString().slice(0, 30), left: l, right: rt });
    }
  }
  return out;
}

export async function gridAudit(page, file = process.env.GRID_AUDIT) {
  if (!file) return [];
  const rows = await page.evaluate(probe);
  if (rows.length) {
    const url = page.url().split("/v4/")[1] || page.url();
    const tab = await page.locator('[role=tab][aria-selected="true"]').first().textContent({ timeout: 200 }).catch(() => "");
    for (const r of rows) appendFileSync(file, JSON.stringify({ url, tab: (tab || "").trim(), ...r }) + "\n");
  }
  return rows;
}
