/* UI-conformance fixtures for Log Analytics workspaces (Microsoft.OperationalInsights ARM
 * control plane). See servicebus/fixtures.mjs for the same contract. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const WS = "uiclaw";
const AV = "api-version=2022-10-01";
const wsPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.OperationalInsights/workspaces/${name}?${AV}`;

async function ensureWorkspace(wire, name = WS) {
  await wire("PUT", wsPath(name), { svc: null, body: { location: "eastus" } }).catch(() => {});
}

export default {
  "az-workspace": async (wire) => { await ensureWorkspace(wire); },

  "live-workspace": async (wire, uniq) => { await wire("PUT", wsPath(uniq), { svc: null, body: { location: "eastus" } }); return uniq; },

  // Each of these mints a FRESH workspace named `uniq` (not the shared "uiclaw") so the page —
  // routed at "#/loganalytics/uic-rg/{live}/…" — resolves {resource-name} to the same string
  // the liveness check searches for; a saved search/table/data source/lock inside the shared
  // workspace would leave the title showing "uiclaw", not the unique live value (see
  // storage/fixtures.mjs's live-container/live-lock for the same pattern).
  "live-savedsearch": async (wire, uniq) => {
    await ensureWorkspace(wire, uniq);
    await wire("PUT", `${wsPath(uniq).split("?")[0]}/savedSearches/${uniq}?${AV}`,
      { svc: null, body: { properties: { category: "uic", displayName: uniq, query: "Heartbeat | take 5" } } });
    return uniq;
  },

  "live-table": async (wire, uniq) => {
    await ensureWorkspace(wire, uniq);
    // The table name must end in _CL, so it can't be exactly `uniq` the way the sibling
    // fixtures below reuse `uniq` for both the workspace and its child — return the
    // WORKSPACE name (what the route's {live} segment needs) rather than the derived table
    // name; the rendered row text ("{uniq}_CL") still contains `uniq` as a substring, which
    // is all the liveness check (checkService's `all.includes(norm(liveText))`) requires.
    await wire("PUT", `${wsPath(uniq).split("?")[0]}/tables/${uniq}_CL?${AV}`, {
      svc: null, body: { properties: { schema: { columns: [{ name: "TimeGenerated", type: "dateTime" }, { name: "Message", type: "string" }] } } },
    });
    return uniq;
  },

  "live-datasource": async (wire, uniq) => {
    await ensureWorkspace(wire, uniq);
    await wire("PUT", `${wsPath(uniq).split("?")[0]}/dataSources/${uniq}?${AV}`,
      { svc: null, body: { kind: "WindowsEvent", properties: { eventLogName: "System" } } });
    return uniq;
  },

  "live-lock": async (wire, uniq) => {
    await ensureWorkspace(wire, uniq);
    await wire("PUT", `${wsPath(uniq).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },

  // A lock write on a fresh workspace is a real ARM mutation, so it lands on the unified
  // Microsoft.Insights/eventtypes feed (core/azure_arm_core.py) — the workspace NAME becomes
  // the activity entry's resourceId, so it is the uniquely-named thing to look for (same
  // pattern as servicebus/fixtures.mjs's live-activity).
  "live-activity": async (wire, uniq) => {
    await ensureWorkspace(wire, uniq);
    await wire("PUT", `${wsPath(uniq).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },
};
