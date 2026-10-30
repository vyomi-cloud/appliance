/* Liveness fixtures for consoles/tests/ui-conformance.mjs — each creates a uniquely named
 * resource over the native wire (no UI) and returns the text the page must then show. */
const PROJECT = "vyomi-project";

export default {
  "mon-dashboard": async (wire, uniq) => {
    const name = `vy-dash-${uniq}`;
    await wire("POST", `/v1/projects/${PROJECT}/dashboards`, { svc: null, body: { displayName: name } });
    return name;
  },
  "mon-uptime": async (wire, uniq) => {
    const name = `vy-uptime-${uniq}`;
    await wire("POST", `/v3/projects/${PROJECT}/uptimeCheckConfigs`, { svc: null, body: {
      displayName: name, monitoredResource: { type: "uptime_url", labels: { host: "example.com" } },
      httpCheck: { path: "/" }, period: "60s", timeout: "10s",
    } });
    return name;
  },
  "mon-synthetic": async (wire, uniq) => {
    const name = `vy-synthetic-${uniq}`;
    await wire("POST", `/v3/projects/${PROJECT}/uptimeCheckConfigs`, { svc: null, body: {
      displayName: name, monitoredResource: { type: "uptime_url", labels: { host: "synthetic" } },
      syntheticMonitor: { cloudFunctionV2: { name: `projects/${PROJECT}/locations/us-central1/functions/f` } },
      period: "300s", timeout: "10s",
    } });
    return name;
  },
  "mon-service": async (wire, uniq) => {
    const name = `vy-service-${uniq}`;
    await wire("POST", `/v3/projects/${PROJECT}/services`, { svc: null, body: { displayName: name } });
    return name;
  },
  "mon-group": async (wire, uniq) => {
    const name = `vy-group-${uniq}`;
    await wire("POST", `/v3/projects/${PROJECT}/groups`, { svc: null, body: { displayName: name, filter: 'resource.type = "gce_instance"' } });
    return name;
  },
  "mon-principal": async (wire, uniq) => {
    const member = `user:${uniq}@example.com`;
    await wire("POST", `/v1/projects/${PROJECT}:setIamPolicy`, { svc: null,
      body: { policy: { bindings: [{ role: "roles/monitoring.viewer", members: [member] }] } } });
    return member;
  },
  "mon-error-entry": async (wire, uniq) => {
    const msg = `vy-error-${uniq}`;
    await wire("POST", "/v2/entries:write", { svc: null, body: {
      logName: `projects/${PROJECT}/logs/vy-smoke`, resource: { type: "global" },
      entries: [{ severity: "ERROR", textPayload: msg }],
    } });
    return msg;
  },
  "mon-alertpolicy": async (wire, uniq) => {
    const name = `vy-policy-${uniq}`;
    await wire("POST", `/v3/projects/${PROJECT}/alertPolicies`, { svc: null, body: {
      displayName: name, conditions: [{ displayName: "cond", conditionThreshold: {
        filter: 'metric.type="compute.googleapis.com/instance/cpu/utilization"', comparison: "COMPARISON_GT", thresholdValue: 0.8,
      } }], combiner: "OR",
    } });
    return name;
  },
};
