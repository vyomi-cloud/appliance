/* UI-conformance fixtures for EventBridge (+ Scheduler). See s3/fixtures.mjs for the contract:
 * plain setup fixtures create a FIXED-name resource a route can target by name; "live-*"
 * fixtures create a UNIQUELY named resource and return that name, proving the page isn't
 * static (it must show that exact name after the fixture runs). */
const EV = (op) => ({ svc: "events", target: `AWSEvents.${op}` });
const SCHED = () => ({ svc: "scheduler" });

const DEFAULT_BUS_ARN = "arn:aws:events:us-east-1:123456789012:event-bus/default";

export default {
  // Fixed-name setup fixtures (a route can target these by name).
  "eb-bus": async (wire) => { await wire("POST", "/", { ...EV("CreateEventBus"), body: { Name: "uic-bus" } }).catch(() => {}); return "uic-bus"; },
  "eb-rule": async (wire) => {
    await wire("POST", "/", { ...EV("PutRule"), body: { Name: "uic-rule", EventBusName: "default", EventPattern: JSON.stringify({ source: ["uic.fixture"] }) } });
    return "uic-rule";
  },

  // Liveness: a uniquely named resource the page must display.
  "live-bus": async (wire, uniq) => { await wire("POST", "/", { ...EV("CreateEventBus"), body: { Name: uniq } }); return uniq; },
  "live-rule": async (wire, uniq) => {
    await wire("POST", "/", { ...EV("PutRule"), body: { Name: uniq, EventBusName: "default", EventPattern: JSON.stringify({ source: ["uic.live"] }) } });
    return uniq;
  },
  "live-rule-on-bus": async (wire, uniq) => {
    await wire("POST", "/", { ...EV("CreateEventBus"), body: { Name: "uic-bus" } }).catch(() => {});
    await wire("POST", "/", { ...EV("PutRule"), body: { Name: uniq, EventBusName: "uic-bus", EventPattern: JSON.stringify({ source: ["uic.live"] }) } });
    return uniq;
  },
  // The rule's Description is rendered as plain text (not an <input> value, which a
  // DOM text-node walker can't see) — a reliable liveness proof for rule-detail's
  // "Rule details" KeyValue panel.
  "live-rule-description": async (wire, uniq) => {
    await wire("POST", "/", { ...EV("PutRule"), body: { Name: "uic-rule", EventBusName: "default", EventPattern: JSON.stringify({ source: ["uic.fixture"] }), Description: uniq } });
    return uniq;
  },
  "live-archive": async (wire, uniq) => {
    await wire("POST", "/", { ...EV("CreateArchive"), body: { ArchiveName: uniq, EventSourceArn: DEFAULT_BUS_ARN } });
    return uniq;
  },
  "live-scheduled-rule": async (wire, uniq) => {
    await wire("POST", "/", { ...EV("PutRule"), body: { Name: uniq, EventBusName: "default", ScheduleExpression: "rate(5 minutes)" } });
    return uniq;
  },
  "live-schedule": async (wire, uniq) => {
    await wire("POST", `/schedules/${uniq}`, { ...SCHED(), body: { GroupName: "default", ScheduleExpression: "rate(5 minutes)", Target: { Arn: "arn:aws:sqs:us-east-1:123456789012:uic-q" } } });
    return uniq;
  },
  "live-schedule-group": async (wire, uniq) => {
    await wire("POST", `/schedule-groups/${uniq}`, SCHED());
    return uniq;
  },
};
