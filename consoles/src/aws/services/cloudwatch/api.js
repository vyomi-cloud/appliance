/* CloudWatch (metrics/alarms/dashboards) + CloudWatch Logs over the native wire.
 * CloudWatch speaks JSON 1.0 under X-Amz-Target GraniteServiceVersion20100801.<Op>;
 * CloudWatch Logs speaks JSON 1.1 under Logs_20140328.<Op>. See core/cloudwatch_core.py
 * and core/logs_core.py for the engines both protocols are served from. */
import { awsJson } from "../../../common/wire.js";

export const REGION = "us-east-1";
export const ACCOUNT_ID = "123456789012";
export const alarmArn = (name) => `arn:aws:cloudwatch:${REGION}:${ACCOUNT_ID}:alarm:${name}`;
export const dashboardArn = (name) => `arn:aws:cloudwatch::${ACCOUNT_ID}:dashboard/${name}`;

const CW = (op, payload = {}) => awsJson("monitoring", `GraniteServiceVersion20100801.${op}`, payload);
const LG = (op, payload = {}) => awsJson("logs", `Logs_20140328.${op}`, payload, { version: "1.1" });

// ── Metrics ──────────────────────────────────────────────────────────────────────────
export const putMetricData = (namespace, metricData) => CW("PutMetricData", { Namespace: namespace, MetricData: metricData });
export const listMetrics = (params = {}) => CW("ListMetrics", params).then((r) => r.Metrics || []);
export const getMetricStatistics = (params) => CW("GetMetricStatistics", params).then((r) => r.Datapoints || []);
export const getMetricData = (queries, startTime, endTime, extra = {}) =>
  CW("GetMetricData", { MetricDataQueries: queries, StartTime: startTime, EndTime: endTime, ...extra }).then((r) => r.MetricDataResults || []);

// ── Alarms ───────────────────────────────────────────────────────────────────────────
export const putMetricAlarm = (alarm) => CW("PutMetricAlarm", alarm);
export const putCompositeAlarm = (alarm) => CW("PutCompositeAlarm", alarm);
export const describeAlarms = (params = {}) => CW("DescribeAlarms", params);
export const describeAlarmsForMetric = (params) => CW("DescribeAlarmsForMetric", params).then((r) => r.MetricAlarms || []);
export const deleteAlarms = (names) => CW("DeleteAlarms", { AlarmNames: names });
export const setAlarmState = (name, state, reason) => CW("SetAlarmState", { AlarmName: name, StateValue: state, StateReason: reason });
export const enableAlarmActions = (names) => CW("EnableAlarmActions", { AlarmNames: names });
export const disableAlarmActions = (names) => CW("DisableAlarmActions", { AlarmNames: names });
export const describeAlarmHistory = (params) => CW("DescribeAlarmHistory", params).then((r) => r.AlarmHistoryItems || []);
export const putAnomalyDetector = (params) => CW("PutAnomalyDetector", params);
export const describeAnomalyDetectors = (params = {}) => CW("DescribeAnomalyDetectors", params).then((r) => r.AnomalyDetectors || []);
export const putInsightRule = (ruleName, ruleDefinition) => CW("PutInsightRule", { RuleName: ruleName, RuleDefinition: JSON.stringify(ruleDefinition) });
export const describeInsightRules = (params = {}) => CW("DescribeInsightRules", params).then((r) => r.InsightRules || []);
export const deleteInsightRules = (ruleNames) => CW("DeleteInsightRules", { RuleNames: ruleNames });
export const getInsightRuleReport = (ruleName, startTime, endTime, maxContributorCount = 10) =>
  CW("GetInsightRuleReport", { RuleName: ruleName, StartTime: startTime, EndTime: endTime, MaxContributorCount: maxContributorCount });

// ── Dashboards ───────────────────────────────────────────────────────────────────────
export const putDashboard = (name, body) => CW("PutDashboard", { DashboardName: name, DashboardBody: JSON.stringify(body) });
export const getDashboard = (name) => CW("GetDashboard", { DashboardName: name });
export const listDashboards = () => CW("ListDashboards", {}).then((r) => r.DashboardEntries || []);
export const deleteDashboards = (names) => CW("DeleteDashboards", { DashboardNames: names });

// ── Tags (shared across alarms / dashboards) ────────────────────────────────────────
export const tagResource = (arn, tags) => CW("TagResource", { ResourceARN: arn, Tags: tags });
export const untagResource = (arn, keys) => CW("UntagResource", { ResourceARN: arn, TagKeys: keys });
export const listTagsForResource = (arn) => CW("ListTagsForResource", { ResourceARN: arn }).then((r) => r.Tags || []);

// ── Logs: log groups ─────────────────────────────────────────────────────────────────
export const createLogGroup = (name, opts = {}) => LG("CreateLogGroup", { logGroupName: name, ...opts });
export const deleteLogGroup = (name) => LG("DeleteLogGroup", { logGroupName: name });
export const describeLogGroups = (params = {}) => LG("DescribeLogGroups", params).then((r) => r.logGroups || []);
export const putRetentionPolicy = (name, days) => LG("PutRetentionPolicy", { logGroupName: name, retentionInDays: days });
export const deleteRetentionPolicy = (name) => LG("DeleteRetentionPolicy", { logGroupName: name });
export const associateKmsKey = (name, kmsKeyId) => LG("AssociateKmsKey", { logGroupName: name, kmsKeyId });
export const disassociateKmsKey = (name) => LG("DisassociateKmsKey", { logGroupName: name });
export const updateLogGroupDeletionProtection = (name, enabled) => LG("UpdateLogGroupDeletionProtection", { logGroupName: name, deletionProtectionEnabled: enabled });
export const putDataProtectionPolicy = (name, policyDocument) => LG("PutDataProtectionPolicy", { logGroupIdentifier: name, policyDocument: JSON.stringify(policyDocument) });
export const getDataProtectionPolicy = (name) => LG("GetDataProtectionPolicy", { logGroupIdentifier: name }).then((r) => ({ ...r, policyDocument: r.policyDocument ? JSON.parse(r.policyDocument) : null }));
export const deleteDataProtectionPolicy = (name) => LG("DeleteDataProtectionPolicy", { logGroupIdentifier: name });
export const putIndexPolicy = (name, fields) => LG("PutIndexPolicy", { logGroupIdentifier: name, policyDocument: JSON.stringify({ fields }) });
export const getIndexPolicy = (name) => LG("GetIndexPolicy", { logGroupIdentifier: name }).then((r) => JSON.parse(r.indexPolicyDocument.policyDocument).fields);
export const deleteIndexPolicy = (name) => LG("DeleteIndexPolicy", { logGroupIdentifier: name });
export const putTransformer = (name, transformerConfig) => LG("PutTransformer", { logGroupIdentifier: name, transformerConfig });
export const getTransformer = (name) => LG("GetTransformer", { logGroupIdentifier: name }).then((r) => r.transformerConfig);
export const deleteTransformer = (name) => LG("DeleteTransformer", { logGroupIdentifier: name });
export const tagLogGroup = (name, tags) => LG("TagLogGroup", { logGroupName: name, tags });
export const untagLogGroup = (name, tagKeys) => LG("UntagLogGroup", { logGroupName: name, tags: tagKeys });
export const listTagsLogGroup = (name) => LG("ListTagsLogGroup", { logGroupName: name }).then((r) => r.tags || {});

// ── Logs: streams + events ───────────────────────────────────────────────────────────
export const createLogStream = (group, stream) => LG("CreateLogStream", { logGroupName: group, logStreamName: stream });
export const deleteLogStream = (group, stream) => LG("DeleteLogStream", { logGroupName: group, logStreamName: stream });
export const describeLogStreams = (group, params = {}) => LG("DescribeLogStreams", { logGroupName: group, ...params }).then((r) => r.logStreams || []);
export const putLogEvents = (group, stream, events) => LG("PutLogEvents", { logGroupName: group, logStreamName: stream, logEvents: events });
export const getLogEvents = (group, stream, params = {}) => LG("GetLogEvents", { logGroupName: group, logStreamName: stream, ...params }).then((r) => r.events || []);
export const filterLogEvents = (group, params = {}) => LG("FilterLogEvents", { logGroupName: group, ...params }).then((r) => r.events || []);

// ── Logs: metric / subscription filters ─────────────────────────────────────────────
export const putMetricFilter = (group, name, pattern, transformations) =>
  LG("PutMetricFilter", { logGroupName: group, filterName: name, filterPattern: pattern, metricTransformations: transformations });
export const describeMetricFilters = (group) => LG("DescribeMetricFilters", { logGroupName: group }).then((r) => r.metricFilters || []);
export const deleteMetricFilter = (group, name) => LG("DeleteMetricFilter", { logGroupName: group, filterName: name });
export const testMetricFilter = (pattern, messages) => LG("TestMetricFilter", { filterPattern: pattern, logEventMessages: messages }).then((r) => r.matches || []);
export const putSubscriptionFilter = (group, name, pattern, destinationArn) =>
  LG("PutSubscriptionFilter", { logGroupName: group, filterName: name, filterPattern: pattern, destinationArn });
export const describeSubscriptionFilters = (group) => LG("DescribeSubscriptionFilters", { logGroupName: group }).then((r) => r.subscriptionFilters || []);
export const deleteSubscriptionFilter = (group, name) => LG("DeleteSubscriptionFilter", { logGroupName: group, filterName: name });

// ── Logs Insights ────────────────────────────────────────────────────────────────────
export const startQuery = (params) => LG("StartQuery", params).then((r) => r.queryId);
export const getQueryResults = (queryId) => LG("GetQueryResults", { queryId });
export const stopQuery = (queryId) => LG("StopQuery", { queryId });
export const describeQueries = (params = {}) => LG("DescribeQueries", params).then((r) => r.queries || []);
