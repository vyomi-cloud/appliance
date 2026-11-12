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

// ── S3 Control: Multi-Region Access Points ──
const MR = (method, path, opts = {}) => ACCT(method, path, opts);
const mrapOf = (a, extra = {}) => ({
  name: a.Name, alias: a.Alias, created: a.CreatedAt, status: a.Status, arn: `arn:aws:s3::${ACCOUNT}:accesspoint/${a.Alias}`,
  regions: asList(a.Regions?.Region).map((r) => ({ bucket: r.Bucket, region: r.Region })), ...extra,
});
export async function listMrap() {
  const r = await MR("GET", "mrap/instances");
  return asList(r.ListMultiRegionAccessPointsResult?.AccessPoints?.AccessPoint).map((a) => mrapOf(a));
}
export async function getMrapDetail(name) {
  const g = (await MR("GET", `mrap/instances/${name}`)).GetMultiRegionAccessPointResult?.AccessPoint || {};
  const m = mrapOf(g);
  const routes = asList((await MR("GET", `mrap/instances/${m.arn}/routes`)).GetMultiRegionAccessPointRoutesResult?.Routes?.Route)
    .map((x) => ({ bucket: x.Bucket, region: x.Region, dial: Number(x.TrafficDialPercentage) }));
  let policy = "";
  try { policy = (await MR("GET", `mrap/instances/${name}/policy`)).GetMultiRegionAccessPointPolicyResult?.Policy?.Established?.Policy || ""; }
  catch (e) { if (e.status !== 404) throw e; }
  return { ...m, routes, policy };
}
export async function createMrap(name, buckets) {
  const body = `<?xml version="1.0" encoding="UTF-8"?><CreateMultiRegionAccessPointInput ${CTL_NS}><ClientToken>${crypto.randomUUID()}</ClientToken><Details><Name>${esc(name)}</Name>`
    + `<Regions>${buckets.map((b) => `<Region><Bucket>${esc(b)}</Bucket></Region>`).join("")}</Regions></Details></CreateMultiRegionAccessPointInput>`;
  const r = await MR("POST", "async-requests/mrap/create", { body });
  const token = r.CreateMultiRegionAccessPointResult?.RequestTokenARN;
  return { token, status: await mrapOperationStatus(token) };
}
export async function mrapOperationStatus(token) {
  const r = await MR("GET", `async-requests/mrap/${token}`);
  return r.DescribeMultiRegionAccessPointOperationResult?.AsyncOperation?.RequestStatus;
}
export const deleteMrap = (name) => MR("POST", "async-requests/mrap/delete", {
  body: `<?xml version="1.0" encoding="UTF-8"?><DeleteMultiRegionAccessPointInput ${CTL_NS}><ClientToken>${crypto.randomUUID()}</ClientToken><Details><Name>${esc(name)}</Name></Details></DeleteMultiRegionAccessPointInput>`,
});
export const putMrapPolicy = (name, policy) => MR("POST", "async-requests/mrap/put-policy", {
  body: `<?xml version="1.0" encoding="UTF-8"?><PutMultiRegionAccessPointPolicyInput ${CTL_NS}><ClientToken>${crypto.randomUUID()}</ClientToken><Details><Name>${esc(name)}</Name><Policy>${esc(policy)}</Policy></Details></PutMultiRegionAccessPointPolicyInput>`,
});
export const submitMrapRoutes = (arn, routes) => MR("PATCH", `mrap/instances/${arn}/routes`, {
  body: `<?xml version="1.0" encoding="UTF-8"?><SubmitMultiRegionAccessPointRoutesRequest ${CTL_NS}><RouteUpdates>${routes.map((r) => `<Route><Bucket>${esc(r.bucket)}</Bucket><Region>${esc(r.region)}</Region><TrafficDialPercentage>${r.dial}</TrafficDialPercentage></Route>`).join("")}</RouteUpdates></SubmitMultiRegionAccessPointRoutesRequest>`,
});
export async function bucketsWithRegion() {
  const names = (await s3("GET", "/")).ListAllMyBucketsResult;
  const out = [];
  for (const b of asList(names?.Buckets?.Bucket)) {
    let region = "us-east-1";
    try { const c = (await s3("GET", `/${b.Name}`, { query: { location: "" } })).LocationConstraint; if (typeof c === "string" && c) region = c; } catch { /* keep default */ }
    out.push({ name: b.Name, region });
  }
  return out;
}

// ── S3 Control: Access Grants ──
const AG = (method, path, opts = {}) => ACCT(method, `accessgrantsinstance${path ? `/${path}` : ""}`, opts);
export async function getAccessGrantsInstance() {
  try {
    const r = (await AG("GET", "")).GetAccessGrantsInstanceResult || {};
    return { arn: r.AccessGrantsInstanceArn, id: r.AccessGrantsInstanceId, created: r.CreatedAt, idc: r.IdentityCenterArn || "" };
  } catch (e) { if (e.status === 404) return null; throw e; }
}
export const createAccessGrantsInstance = () => AG("POST", "", { body: `<?xml version="1.0" encoding="UTF-8"?><CreateAccessGrantsInstanceRequest ${CTL_NS}></CreateAccessGrantsInstanceRequest>` });
export const deleteAccessGrantsInstance = () => AG("DELETE", "");
export const associateIdentityCenter = (arn) => AG("POST", "identitycenter", { body: `<?xml version="1.0" encoding="UTF-8"?><AssociateAccessGrantsIdentityCenterRequest ${CTL_NS}><IdentityCenterArn>${esc(arn)}</IdentityCenterArn></AssociateAccessGrantsIdentityCenterRequest>` });
export const dissociateIdentityCenter = () => AG("DELETE", "identitycenter");
export async function listAccessGrantsLocations() {
  const r = await AG("GET", "locations");
  return asList(r.ListAccessGrantsLocationsResult?.AccessGrantsLocationsList?.AccessGrantsLocation).map((l) => ({
    id: l.AccessGrantsLocationId, arn: l.AccessGrantsLocationArn, scope: l.LocationScope, role: l.IAMRoleArn, created: l.CreatedAt,
  }));
}
export const createAccessGrantsLocation = (scope, role) => AG("POST", "location", {
  body: `<?xml version="1.0" encoding="UTF-8"?><CreateAccessGrantsLocationRequest ${CTL_NS}><LocationScope>${esc(scope)}</LocationScope><IAMRoleArn>${esc(role)}</IAMRoleArn></CreateAccessGrantsLocationRequest>`,
});
export const deleteAccessGrantsLocation = (id) => AG("DELETE", `location/${id}`);
export async function listAccessGrants() {
  const r = await AG("GET", "grants");
  return asList(r.ListAccessGrantsResult?.AccessGrantsList?.AccessGrant).map((g) => ({
    id: g.AccessGrantId, arn: g.AccessGrantArn, scope: g.GrantScope, permission: g.Permission, locationId: g.AccessGrantsLocationId,
    granteeType: g.Grantee?.GranteeType, grantee: g.Grantee?.GranteeIdentifier, created: g.CreatedAt,
  }));
}
export const createAccessGrant = ({ locationId, subPrefix, granteeType, grantee, permission }) => AG("POST", "grant", {
  body: `<?xml version="1.0" encoding="UTF-8"?><CreateAccessGrantRequest ${CTL_NS}><AccessGrantsLocationId>${esc(locationId)}</AccessGrantsLocationId>`
    + `<AccessGrantsLocationConfiguration><S3SubPrefix>${esc(subPrefix || "")}</S3SubPrefix></AccessGrantsLocationConfiguration>`
    + `<Grantee><GranteeType>${granteeType}</GranteeType><GranteeIdentifier>${esc(grantee)}</GranteeIdentifier></Grantee><Permission>${permission}</Permission></CreateAccessGrantRequest>`,
});
export const deleteAccessGrant = (id) => AG("DELETE", `grant/${id}`);
export async function getDataAccess(target, permission) {
  const r = (await AG("GET", "dataaccess", { query: { target, permission } })).GetDataAccessResult || {};
  return { accessKeyId: r.Credentials?.AccessKeyId, secretAccessKey: r.Credentials?.SecretAccessKey, sessionToken: r.Credentials?.SessionToken,
    expiration: r.Credentials?.Expiration, matched: r.MatchedGrantTarget };
}

// ── S3 Control: Batch Operations ──
const TERMINAL = ["Complete", "Failed", "Cancelled"];
export const JOB_TERMINAL = TERMINAL;
const jobOf = (j) => {
  const p = j.ProgressSummary || {};
  return {
    id: j.JobId, status: j.Status, operation: typeof j.Operation === "string" ? j.Operation : Object.keys(j.Operation || {})[0] || "",
    priority: Number(j.Priority), description: j.Description || "", created: j.CreationTime, terminated: j.TerminationDate,
    total: Number(p.TotalNumberOfTasks || 0), ok: Number(p.NumberOfTasksSucceeded || 0), failed: Number(p.NumberOfTasksFailed || 0),
    reason: j.StatusUpdateReason || "", cause: j.SuspendedCause || "", role: j.RoleArn || "", confirm: j.ConfirmationRequired === "true",
    failures: asList(j.FailureReasons?.member).map((f) => `${f.FailureCode}: ${f.FailureReason}`),
    manifest: j.Manifest ? { format: j.Manifest.Spec?.Format, arn: j.Manifest.Location?.ObjectArn } : null,
    report: j.Report ? { enabled: j.Report.Enabled === "true", bucket: (j.Report.Bucket || "").replace("arn:aws:s3:::", ""), prefix: j.Report.Prefix || "", scope: j.Report.ReportScope } : null,
  };
};
export async function listJobs() {
  const r = await ACCT("GET", "jobs", { query: { maxResults: "100" } });
  return asList(r.ListJobsResult?.Jobs?.member).map(jobOf);
}
export async function describeJob(id) {
  return jobOf((await ACCT("GET", `jobs/${id}`)).DescribeJobResult?.Job || {});
}
export const updateJobStatus = (id, status, reason) => ACCT("POST", `jobs/${id}/status`, { query: { requestedJobStatus: status, statusUpdateReason: reason } });
export const updateJobPriority = (id, priority) => ACCT("POST", `jobs/${id}/priority`, { query: { priority: String(priority) } });
export async function getJobTags(id) {
  return asList((await ACCT("GET", `jobs/${id}/tagging`)).GetJobTaggingResult?.Tags?.member).map((t) => ({ key: t.Key, value: t.Value }));
}
export const putJobTags = (id, tags) => ACCT("PUT", `jobs/${id}/tagging`, {
  body: `<?xml version="1.0" encoding="UTF-8"?><PutJobTaggingRequest ${CTL_NS}><Tags>${tags.map((t) => `<member><Key>${esc(t.key)}</Key><Value>${esc(t.value)}</Value></member>`).join("")}</Tags></PutJobTaggingRequest>`,
});
export const BATCH_OPERATIONS = [
  { value: "S3PutObjectCopy", label: "Copy", description: "Copy each object to a destination bucket" },
  { value: "LambdaInvoke", label: "Invoke AWS Lambda function", description: "Invoke a Lambda function for each object" },
  { value: "S3PutObjectTagging", label: "Replace all object tags", description: "Set the same tag set on every object" },
  { value: "S3DeleteObjectTagging", label: "Delete all object tags", description: "Remove every tag from each object" },
  { value: "S3PutObjectAcl", label: "Replace access control list (ACL)", description: "Apply a canned ACL" },
  { value: "S3InitiateRestoreObject", label: "Restore", description: "Restore archived (Glacier) objects" },
  { value: "S3PutObjectLegalHold", label: "Object Lock legal hold", description: "Turn a legal hold on or off" },
  { value: "S3PutObjectRetention", label: "Object Lock retention", description: "Set a retention mode and date" },
  { value: "S3ReplicateObject", label: "Replicate", description: "Replicate objects using the source bucket's replication rules" },
];
export function operationXml(op, p) {
  switch (op) {
    case "S3PutObjectCopy": return `<S3PutObjectCopy><TargetResource>arn:aws:s3:::${esc(p.targetBucket)}</TargetResource>${p.targetPrefix ? `<TargetKeyPrefix>${esc(p.targetPrefix)}</TargetKeyPrefix>` : ""}${p.storageClass ? `<StorageClass>${p.storageClass}</StorageClass>` : ""}</S3PutObjectCopy>`;
    case "LambdaInvoke": return `<LambdaInvoke><FunctionArn>${esc(p.functionArn)}</FunctionArn><InvocationSchemaVersion>${p.schema || "1.0"}</InvocationSchemaVersion></LambdaInvoke>`;
    case "S3PutObjectTagging": return `<S3PutObjectTagging><TagSet>${p.tags.map((t) => `<member><Key>${esc(t.key)}</Key><Value>${esc(t.value)}</Value></member>`).join("")}</TagSet></S3PutObjectTagging>`;
    case "S3DeleteObjectTagging": return "<S3DeleteObjectTagging/>";
    case "S3PutObjectAcl": return `<S3PutObjectAcl><AccessControlPolicy><CannedAccessControlList>${p.acl}</CannedAccessControlList></AccessControlPolicy></S3PutObjectAcl>`;
    case "S3InitiateRestoreObject": return `<S3InitiateRestoreObject><ExpirationInDays>${p.days || 1}</ExpirationInDays><GlacierJobTier>${p.tier || "STANDARD"}</GlacierJobTier></S3InitiateRestoreObject>`;
    case "S3PutObjectLegalHold": return `<S3PutObjectLegalHold><LegalHold><Status>${p.hold}</Status></LegalHold></S3PutObjectLegalHold>`;
    case "S3PutObjectRetention": return `<S3PutObjectRetention><Retention><Mode>${p.mode}</Mode><RetainUntilDate>${new Date(p.until).toISOString()}</RetainUntilDate></Retention></S3PutObjectRetention>`;
    default: return "<S3ReplicateObject/>";
  }
}
/** CreateJob. `manifest` {bucket,key,format,fields}; `report` {enabled,bucket,prefix,scope}. Returns the JobId. */
export async function createJob({ operation, params, manifest, report, priority, description, confirm, role }) {
  const head = await s3("HEAD", `/${manifest.bucket}/${manifest.key}`, { raw: true }).catch(() => null);
  const etag = head?.headers?.get("etag") || "";
  const body = `<?xml version="1.0" encoding="UTF-8"?><CreateJobRequest ${CTL_NS}><ConfirmationRequired>${!!confirm}</ConfirmationRequired>`
    + `<ClientRequestToken>${crypto.randomUUID()}</ClientRequestToken><Description>${esc(description || "")}</Description><Priority>${priority}</Priority><RoleArn>${esc(role)}</RoleArn>`
    + `<Operation>${operationXml(operation, params)}</Operation>`
    + `<Manifest><Spec><Format>${manifest.format}</Format><Fields>${manifest.fields.map((f) => `<member>${f}</member>`).join("")}</Fields></Spec>`
    + `<Location><ObjectArn>arn:aws:s3:::${esc(manifest.bucket)}/${esc(manifest.key)}</ObjectArn>${etag ? `<ETag>${esc(etag.replaceAll('"', ""))}</ETag>` : ""}</Location></Manifest>`
    + (report.enabled ? `<Report><Bucket>arn:aws:s3:::${esc(report.bucket)}</Bucket><Format>Report_CSV_20180820</Format><Enabled>true</Enabled>${report.prefix ? `<Prefix>${esc(report.prefix)}</Prefix>` : ""}<ReportScope>${report.scope}</ReportScope></Report>`
      : "<Report><Enabled>false</Enabled></Report>")
    + "</CreateJobRequest>";
  return (await ACCT("POST", "jobs", { body })).CreateJobResult?.JobId;
}
export async function listJobReportKeys(j) {
  if (!j.report?.enabled) return [];
  const pre = `${j.report.prefix ? j.report.prefix.replace(/\/+$/, "") + "/" : ""}job-${j.id}/`;
  const r = await s3("GET", `/${j.report.bucket}`, { query: { "list-type": "2", prefix: pre } });
  return asList(r.ListBucketResult?.Contents).map((o) => ({ bucket: j.report.bucket, key: o.Key, size: Number(o.Size || 0) }));
}
