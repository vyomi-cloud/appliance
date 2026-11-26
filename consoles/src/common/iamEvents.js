/* IAM event history client (pure JS, no React): GET <base>/<cloud>/events with filters, GET <base>/<cloud>/events/export?format=csv|json.
 * Row shape (all clouds): {id, time (epoch s), cloud, service, name, principal, resource, outcome: success|denied|error|would_deny, errorCode, readOnly,
 * params, native}; `native` is the cloud's own record (CloudTrail event, Cloud Audit Logs LogEntry, Activity Log event). */
export const OUTCOMES = ["success", "denied", "error", "would_deny"];
export const OUTCOME_LABEL = { success: "Succeeded", denied: "Denied", error: "Failed", would_deny: "Would deny" };
export const EVENT_COPY = {
  aws: { title: "Event history", info: "CloudTrail-style management events for IAM, STS, Roles Anywhere and Access Analyzer, plus requests the IAM gate denied.", name: "Event name", resource: "Resource name" },
  gcp: { title: "IAM activity", info: "Cloud Audit Logs entries for IAM admin, IAM Credentials (impersonation, key creation) and STS exchanges, plus requests the IAM gate denied.", name: "Method", resource: "Resource" },
  azure: { title: "IAM activity log", info: "Activity Log events for role assignments, role definitions, PIM requests and managed identities, plus requests the IAM gate denied.", name: "Operation", resource: "Resource" },
};

export function eventsQuery(filters = {}, extra = {}) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...filters, ...extra })) if (v !== undefined && v !== null && v !== "" && v !== "all") p.set(k, String(v));
  const s = p.toString();
  return s ? "?" + s : "";
}

export function eventsApi(cloud, { base, fetcher } = {}) {
  const f = fetcher || ((...a) => fetch(...a));
  return {
    list: async (filters, limit = 100) => {
      const res = await f(`${base}/${cloud}/events${eventsQuery(filters, { limit })}`);
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw Object.assign(new Error(d.error?.message || d.message || `IAM events HTTP ${res.status}`), { status: res.status });
      return { events: d.events || [], total: d.total ?? (d.events || []).length, truncated: !!d.truncated };
    },
    exportUrl: (filters, format = "csv") => `${base}/${cloud}/events/export${eventsQuery(filters, { format })}`,
  };
}

export const eventTime = (e) => (typeof e.time === "string" ? e.time.replace(/\.\d+Z$/, "Z") : e.ts ? new Date(e.ts * 1000).toISOString().replace(/\.\d+Z$/, "Z") : "");
export const shortPrincipal = (p) => String(p || "").replace(/^arn:aws:(iam|sts)::\d+:/, "");
