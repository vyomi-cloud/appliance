/* console-ui gate: compare UI-conformance before/after an agent run and refuse metric gaming.
 *
 *   node consoles/tests/gate-compare.mjs <before.json> <after.json> <cloud> <service> <base-allowlist.json> <spec-map.json>
 *
 * Fails (exit 1) when:
 *   - fidelity is below MIN_FIDELITY (default 0.90),
 *   - real coverage or the count of present elements went DOWN,
 *   - a page is declared wholly "Not simulated" (honest_page) without being on the
 *     allowlist taken from the BASE branch (agents cannot extend it).
 */
import { readFile } from "node:fs/promises";

const [beforeP, afterP, cloud, svc, allowP, mapP] = process.argv.slice(2);
const MIN = Number(process.env.MIN_FIDELITY || 0.9);
const load = async (p, d) => { try { return JSON.parse(await readFile(p, "utf8")); } catch { return d; } };
const pick = (arr) => (arr || []).find((r) => r.svc === svc) || {};

const before = pick(await load(beforeP, []));
const after = pick(await load(afterP, []));
const allow = new Set((await load(allowP, {}))?.[cloud]?.[svc] || []);
const map = await load(mapP, {});

const problems = [];
if (after.error || after.fidelity === undefined) problems.push(`no UI-conformance result for ${cloud}/${svc}`);
if ((after.fidelity ?? 0) < MIN) problems.push(`fidelity ${(after.fidelity * 100).toFixed(1)}% < ${MIN * 100}%`);
if (before.coverage !== undefined && after.coverage + 1e-9 < before.coverage)
  problems.push(`real coverage dropped ${(before.coverage * 100).toFixed(1)}% → ${(after.coverage * 100).toFixed(1)}%`);
if (before.present !== undefined && after.present < before.present)
  problems.push(`present elements dropped ${before.present} → ${after.present}`);
const unapproved = Object.entries(map).filter(([k, v]) => v && v.honest_page && !allow.has(k)).map(([k]) => k);
if (unapproved.length) problems.push(`honest_page not on the base allowlist: ${unapproved.join(", ")} — build these pages`);

const pct = (x) => (x === undefined ? "—" : `${(x * 100).toFixed(1)}%`);
console.log(`${cloud}/${svc}: fidelity ${pct(before.fidelity)} → ${pct(after.fidelity)}, real coverage ${pct(before.coverage)} → ${pct(after.coverage)}, present ${before.present ?? "—"} → ${after.present ?? "—"}`);
if (problems.length) { console.log("GATE FAILED:\n- " + problems.join("\n- ")); process.exit(1); }
console.log("GATE PASSED");
