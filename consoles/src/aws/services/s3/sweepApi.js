/* S3 sweep-A native-wire calls: event notifications (+ EventBridge), CloudWatch metrics. */
import { asList, authHeader, awsJson, awsRest, s3 } from "../../../common/wire.js";

const esc = (s) => String(s).replace(/[<>&'"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" }[c]));
const NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"';
const KINDS = [
  { kind: "queue", tag: "QueueConfiguration", dest: "Queue", label: "SQS queue" },
  { kind: "topic", tag: "TopicConfiguration", dest: "Topic", label: "SNS topic" },
  { kind: "function", tag: "CloudFunctionConfiguration", dest: "CloudFunction", label: "Lambda function" },
];
export const NOTIFICATION_KINDS = KINDS;

export async function getNotification(b) {
  const r = await s3("GET", `/${b}`, { query: { notification: "" } });
  const n = r.NotificationConfiguration || {};
  const rules = [];
  for (const k of KINDS) {
    for (const x of asList(n[k.tag])) {
      const f = asList(x.Filter?.S3Key?.FilterRule);
      rules.push({
        id: x.Id, kind: k.kind, arn: x[k.dest], events: asList(x.Event),
        prefix: f.find((y) => String(y.Name).toLowerCase() === "prefix")?.Value || "",
        suffix: f.find((y) => String(y.Name).toLowerCase() === "suffix")?.Value || "",
      });
    }
  }
  return { rules, eventBridge: n.EventBridgeConfiguration !== undefined };
}

export function putNotification(b, { rules, eventBridge }) {
  const body = rules.map((r) => {
    const k = KINDS.find((x) => x.kind === r.kind);
    const fr = [["prefix", r.prefix], ["suffix", r.suffix]].filter(([, v]) => v)
      .map(([n, v]) => `<FilterRule><Name>${n}</Name><Value>${esc(v)}</Value></FilterRule>`).join("");
    return `<${k.tag}><Id>${esc(r.id)}</Id>${r.events.map((e) => `<Event>${esc(e)}</Event>`).join("")}`
      + `<${k.dest}>${esc(r.arn)}</${k.dest}>${fr ? `<Filter><S3Key>${fr}</S3Key></Filter>` : ""}</${k.tag}>`;
  }).join("");
  return s3("PUT", `/${b}`, {
    query: { notification: "" },
    body: `<?xml version="1.0" encoding="UTF-8"?><NotificationConfiguration ${NS}>${body}${eventBridge ? "<EventBridgeConfiguration></EventBridgeConfiguration>" : ""}</NotificationConfiguration>`,
  });
}

const CW = (op, payload = {}) => awsJson("monitoring", `GraniteServiceVersion20100801.${op}`, payload);

/** GetMetricStatistics over the native CloudWatch wire -> [{t, v}] oldest first. */
export async function metricSeries(namespace, metricName, dims, { statistic = "Maximum", minutes = 180, period = 60 } = {}) {
  const end = new Date(), start = new Date(end - minutes * 60_000);
  const r = await CW("GetMetricStatistics", {
    Namespace: namespace, MetricName: metricName, Dimensions: dims,
    StartTime: start.toISOString(), EndTime: new Date(+end + 60_000).toISOString(), Period: period, Statistics: [statistic],
  });
  return (r.Datapoints || []).map((p) => ({ t: new Date(p.Timestamp).getTime(), v: Number(p[statistic]), unit: p.Unit }))
    .sort((a, b) => a.t - b.t);
}

/** Account snapshot: totals over every bucket, counted from real ListObjectsV2 pages. */
export async function accountSnapshot(buckets, { maxPages = 50 } = {}) {
  let objects = 0, bytes = 0, truncated = false;
  const perBucket = [];
  for (const b of buckets) {
    let n = 0, sz = 0, token, pages = 0;
    do {
      const r = await s3("GET", `/${b}`, { query: { "list-type": "2", "continuation-token": token } });
      const res = r.ListBucketResult || {};
      for (const o of asList(res.Contents)) { n += 1; sz += Number(o.Size || 0); }
      token = res.IsTruncated === "true" ? res.NextContinuationToken : null;
      pages += 1;
    } while (token && pages < maxPages);
    if (token) truncated = true;
    objects += n; bytes += sz; perBucket.push({ name: b, objects: n, bytes: sz });
  }
  return { buckets: buckets.length, objects, bytes, truncated, perBucket };
}

// ── S3 Control: access points (restXml /v20180820/accesspoint) ──
const ACCOUNT = "123456789012";
const AP = (method, name, { sub = "", query, body } = {}) =>
  s3(method, `/v20180820/accesspoint${name ? `/${name}` : ""}${sub ? `/${sub}` : ""}`, { query, body, headers: { "x-amz-account-id": ACCOUNT } });
const CTL_NS = 'xmlns="http://awss3control.amazonaws.com/doc/2016-08-20/"';

export async function listAccessPoints(bucket) {
  const r = await AP("GET", "", { query: bucket ? { bucket } : undefined });
  return asList(r.ListAccessPointsResult?.AccessPointList?.AccessPoint).map((a) => ({
    name: a.Name, bucket: a.Bucket, networkOrigin: a.NetworkOrigin, vpcId: a.VpcConfiguration?.VpcId || "", arn: a.AccessPointArn, alias: a.Alias,
  }));
}
export const createAccessPoint = (bucket, name, { vpcId = "", blockPublic = true } = {}) => AP("PUT", name, {
  body: `<?xml version="1.0" encoding="UTF-8"?><CreateAccessPointRequest ${CTL_NS}><Bucket>${esc(bucket)}</Bucket>`
    + (vpcId ? `<VpcConfiguration><VpcId>${esc(vpcId)}</VpcId></VpcConfiguration>` : "")
    + `<PublicAccessBlockConfiguration>${["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"].map((k) => `<${k}>${blockPublic}</${k}>`).join("")}</PublicAccessBlockConfiguration></CreateAccessPointRequest>`,
});
export const deleteAccessPoint = (name) => AP("DELETE", name);
export async function getAccessPointPolicy(name) {
  try {
    const r = await AP("GET", name, { sub: "policy" });
    return r.GetAccessPointPolicyResult?.Policy || "";
  } catch (e) { if (e.status === 404) return ""; throw e; }
}
export const putAccessPointPolicy = (name, policy) => AP("PUT", name, {
  sub: "policy", body: `<?xml version="1.0" encoding="UTF-8"?><PutAccessPointPolicyRequest ${CTL_NS}><Policy>${esc(policy)}</Policy></PutAccessPointPolicyRequest>`,
});
export const deleteAccessPointPolicy = (name) => AP("DELETE", name, { sub: "policy" });

// ── S3 Control: account-level Block Public Access ──
const PAB_KEYS = ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"];
export const ACCOUNT_PAB_KEYS = PAB_KEYS;
const ACCT = (method, path, opts = {}) => s3(method, `/v20180820/${path}`, { ...opts, headers: { "x-amz-account-id": ACCOUNT, ...(opts.headers || {}) } });

/** -> {BlockPublicAcls, …} booleans, or null when the account has no configuration. */
export async function getAccountPab() {
  try {
    const r = await ACCT("GET", "configuration/publicAccessBlock");
    const c = r.PublicAccessBlockConfiguration || {};
    return Object.fromEntries(PAB_KEYS.map((k) => [k, String(c[k]) === "true"]));
  } catch (e) { if (e.status === 404) return null; throw e; }
}
export const putAccountPab = (cfg) => ACCT("PUT", "configuration/publicAccessBlock", {
  body: `<?xml version="1.0" encoding="UTF-8"?><PublicAccessBlockConfiguration ${CTL_NS}>${PAB_KEYS.map((k) => `<${k}>${!!cfg[k]}</${k}>`).join("")}</PublicAccessBlockConfiguration>`,
});
export const deleteAccountPab = () => ACCT("DELETE", "configuration/publicAccessBlock");

// ── S3 Express One Zone: directory buckets ──
export const directoryBucketName = (base, zone) => `${base}--${zone}--x-s3`;
export async function listDirectoryBuckets() {
  const out = [];
  let token;
  do {
    const r = await s3("GET", "/", { query: { "continuation-token": token }, headers: authHeader("s3express") });
    const res = r.ListAllMyDirectoryBucketsResult || {};
    out.push(...asList(res.Buckets?.Bucket).map((b) => ({ name: b.Name, created: b.CreationDate, region: b.BucketRegion })));
    token = res.ContinuationToken || null;
  } while (token);
  return out;
}
export const createDirectoryBucket = (name, zone) => s3("PUT", `/${name}`, {
  body: `<?xml version="1.0" encoding="UTF-8"?><CreateBucketConfiguration ${NS}><Location><Name>${esc(zone)}</Name><Type>AvailabilityZone</Type></Location>`
    + "<Bucket><DataRedundancy>SingleAvailabilityZone</DataRedundancy><Type>Directory</Type></Bucket></CreateBucketConfiguration>",
});
export const createSession = async (bucket) => (await s3("GET", `/${bucket}`, { query: { session: "" }, headers: { "x-amz-create-session-mode": "ReadWrite" } })).CreateSessionResult?.Credentials || {};

// ── S3 Control: Object Lambda Access Points ──
const OL = (method, name, { sub = "", body } = {}) => ACCT(method, `accesspointforobjectlambda${name ? `/${name}` : ""}${sub ? `/${sub}` : ""}`, { body });
export async function listObjectLambdaAccessPoints() {
  const r = await OL("GET", "");
  return asList(r.ListAccessPointsForObjectLambdaResult?.ObjectLambdaAccessPointList?.ObjectLambdaAccessPoint).map((a) => ({
    name: a.Name, arn: a.ObjectLambdaAccessPointArn, alias: a.Alias?.Value, aliasStatus: a.Alias?.Status,
  }));
}
export async function getObjectLambdaAccessPoint(name) {
  const [g, c] = await Promise.all([OL("GET", name), OL("GET", name, { sub: "configuration" })]);
  const cfg = c.GetAccessPointConfigurationForObjectLambdaResult?.Configuration || {};
  const t = asList(cfg.TransformationConfigurations?.TransformationConfiguration);
  return {
    name, created: g.GetAccessPointForObjectLambdaResult?.CreationDate, alias: g.GetAccessPointForObjectLambdaResult?.Alias?.Value,
    supporting: cfg.SupportingAccessPoint, metrics: cfg.CloudWatchMetricsEnabled === "true",
    allowed: asList(cfg.AllowedFeatures?.AllowedFeature),
    transformations: t.map((x) => ({ actions: asList(x.Actions?.Action), functionArn: x.ContentTransformation?.AwsLambda?.FunctionArn, payload: x.ContentTransformation?.AwsLambda?.FunctionPayload || "" })),
  };
}
const olapBody = (root, { supporting, functionArn, payload = "", actions = ["GetObject"], allowed = [], metrics = false }) =>
  `<?xml version="1.0" encoding="UTF-8"?><${root} ${CTL_NS}><Configuration><SupportingAccessPoint>${esc(supporting)}</SupportingAccessPoint>`
  + `<CloudWatchMetricsEnabled>${!!metrics}</CloudWatchMetricsEnabled><AllowedFeatures>${allowed.map((f) => `<AllowedFeature>${f}</AllowedFeature>`).join("")}</AllowedFeatures>`
  + `<TransformationConfigurations><TransformationConfiguration><Actions>${actions.map((a) => `<Action>${a}</Action>`).join("")}</Actions><ContentTransformation><AwsLambda>`
  + `<FunctionArn>${esc(functionArn)}</FunctionArn>${payload ? `<FunctionPayload>${esc(payload)}</FunctionPayload>` : ""}</AwsLambda></ContentTransformation></TransformationConfiguration></TransformationConfigurations></Configuration></${root}>`;
export const createObjectLambdaAccessPoint = (name, cfg) => OL("PUT", name, { body: olapBody("CreateAccessPointForObjectLambdaRequest", cfg) });
export const deleteObjectLambdaAccessPoint = (name) => OL("DELETE", name);
export async function listLambdaFunctions() {
  const r = await awsRest("lambda", "GET", "/2015-03-31/functions");
  return (r.Functions || []).map((f) => ({ name: f.FunctionName, arn: f.FunctionArn }));
}

/** Flat (no delimiter) ListObjectsV2 of a directory bucket -> [{key, size, modified, storageClass}]. */
export async function listBucketObjectsFlat(bucket) {
  const out = [];
  let token;
  do {
    const r = await s3("GET", `/${bucket}`, { query: { "list-type": "2", "continuation-token": token } });
    const res = r.ListBucketResult || {};
    out.push(...asList(res.Contents).map((o) => ({ key: o.Key, size: Number(o.Size || 0), modified: o.LastModified, storageClass: o.StorageClass || "STANDARD" })));
    token = res.IsTruncated === "true" ? res.NextContinuationToken : null;
  } while (token);
  return out;
}
