/* Create alarm. Each wizard step in the real console becomes a Tab here (not a gated
 * Cloudscape <Wizard>, which only mounts its active step's content) so every step's
 * fields are reachable the way UI conformance — and a real user — can get to them.
 * Default data source is Metrics (a standard metric alarm); choosing Alarms switches to
 * building a composite alarm from existing alarms' states. */
import { useEffect, useMemo, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Multiselect from "@cloudscape-design/components/multiselect";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tabs from "@cloudscape-design/components/tabs";
import TagEditor from "@cloudscape-design/components/tag-editor";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { PERIOD_OPTIONS } from "./common.jsx";
import * as api from "./api.js";

const TAG_I18N = {
  keyHeader: "Key", valueHeader: "Value", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo",
  undoPrompt: "Removed upon saving", loading: "Loading tags", keyPlaceholder: "Key", valuePlaceholder: "Value",
  emptyTags: "No tags associated with this resource.", emptyKeyError: "You must specify a tag key",
  maxKeyCharLengthError: "128 character limit.", maxValueCharLengthError: "256 character limit.",
  duplicateKeyError: "Unique key required.", invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.", awsPrefixError: "Cannot start with aws:",
  tagLimit: (a) => `You can add up to ${a} more tags.`, tagLimitReached: () => "Tag limit reached.", tagLimitExceeded: () => "Tag limit exceeded.",
};

const COMPARISONS = [
  { label: "Greater", value: "GreaterThanThreshold" }, { label: "Greater/Equal", value: "GreaterThanOrEqualToThreshold" },
  { label: "Lower/Equal", value: "LessThanOrEqualToThreshold" }, { label: "Lower", value: "LessThanThreshold" },
];
const MISSING_DATA = [
  { label: "Treat missing data as missing", value: "missing" }, { label: "Treat missing data as breaching threshold", value: "breaching" },
  { label: "Treat missing data as not breaching threshold", value: "notBreaching" }, { label: "Ignore missing data", value: "ignore" },
];

function MetricPicker({ namespace, setNamespace, metricName, setMetricName }) {
  const [open, setOpen] = useState(!namespace);
  const metrics = useAsync(() => api.listMetrics({}), []);
  const namespaces = useMemo(() => [...new Set((metrics.data || []).map((m) => m.Namespace))].sort(), [metrics.data]);
  const names = useMemo(() => [...new Set((metrics.data || []).filter((m) => m.Namespace === namespace).map((m) => m.MetricName))].sort(), [metrics.data, namespace]);
  return (
    <SpaceBetween size="s">
      {!open && namespace && metricName ? (
        <Box>Metric: <b>{namespace} / {metricName}</b> <Button variant="inline-link" onClick={() => setOpen(true)}>Change</Button></Box>
      ) : (
        <SpaceBetween direction="horizontal" size="s">
          <Select placeholder="Select a namespace" selectedOption={namespace ? { label: namespace, value: namespace } : null}
            onChange={({ detail }) => { setNamespace(detail.selectedOption.value); setMetricName(null); }}
            options={namespaces.map((n) => ({ label: n, value: n }))} ariaLabel="Namespace" />
          <Select placeholder="Select a metric" disabled={!namespace} selectedOption={metricName ? { label: metricName, value: metricName } : null}
            onChange={({ detail }) => { setMetricName(detail.selectedOption.value); setOpen(false); }}
            options={names.map((n) => ({ label: n, value: n }))} ariaLabel="Metric name" />
        </SpaceBetween>
      )}
    </SpaceBetween>
  );
}

export default function CreateAlarm({ query }) {
  const notify = useNotify();
  const editingName = query?.edit || null;
  const initialSource = useMemo(() => { const s = sessionStorage.getItem("cw.alarmSource"); sessionStorage.removeItem("cw.alarmSource"); return s || "Metrics"; }, []);
  const [dataSource, setDataSource] = useState(initialSource);
  const [type, setType] = useState("Classic");
  const [namespace, setNamespace] = useState(null);
  const [metricName, setMetricName] = useState(null);
  const [statistic, setStatistic] = useState("Average");
  const [period, setPeriod] = useState("300");
  const [thresholdType, setThresholdType] = useState("Static");
  const [comparison, setComparison] = useState("GreaterThanThreshold");
  const [anomalyComparison, setAnomalyComparison] = useState("LessThanLowerOrGreaterThanUpperThreshold");
  const [anomalyStdDevs, setAnomalyStdDevs] = useState("2");
  const [threshold, setThreshold] = useState("");
  const [evalPeriods, setEvalPeriods] = useState(1);
  const [datapointsToAlarm, setDatapointsToAlarm] = useState(1);
  const [missingData, setMissingData] = useState("missing");

  const alarmsList = useAsync(() => api.describeAlarms({}), []);
  const [compositeAlarms, setCompositeAlarms] = useState([]);
  const [compositeOp, setCompositeOp] = useState("OR");

  const [stateTrigger, setStateTrigger] = useState("In alarm");
  const [snsArn, setSnsArn] = useState("");
  const [lambdaArn, setLambdaArn] = useState("");

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState([]);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!editingName) return;
    (async () => {
      const res = await api.describeAlarms({ AlarmNames: [editingName] });
      const rec = (res.MetricAlarms || res.CompositeAlarms || [])[0];
      if (!rec) return;
      setName(rec.AlarmName);
      setDescription(rec.AlarmDescription || "");
      if (rec.AlarmRule) {
        setDataSource("Alarms");
        setCompositeAlarms([...new Set(rec.AlarmRule.match(/"([^"]+)"/g) || [])].map((s) => s.replace(/"/g, "")));
        setCompositeOp(rec.AlarmRule.includes(" AND ") ? "AND" : "OR");
      } else {
        const band = rec.Metrics?.find((m) => /^ANOMALY_DETECTION_BAND\(/i.test(m.Expression || ""));
        const bandMetric = band && rec.Metrics.find((m) => m.Id === band.Expression.match(/\(\s*(\w+)/)[1]);
        if (band && bandMetric?.MetricStat) {
          setThresholdType("Anomaly detection");
          setNamespace(bandMetric.MetricStat.Metric.Namespace); setMetricName(bandMetric.MetricStat.Metric.MetricName);
          setStatistic(bandMetric.MetricStat.Stat); setPeriod(String(bandMetric.MetricStat.Period));
          setAnomalyComparison(rec.ComparisonOperator);
          setAnomalyStdDevs(String((band.Expression.match(/,\s*([\d.]+)\s*\)/) || [, "2"])[1]));
        } else {
          setNamespace(rec.Namespace); setMetricName(rec.MetricName);
          setStatistic(rec.Statistic || rec.ExtendedStatistic); setPeriod(String(rec.Period));
          setComparison(rec.ComparisonOperator); setThreshold(String(rec.Threshold));
        }
        setEvalPeriods(rec.EvaluationPeriods); setDatapointsToAlarm(rec.DatapointsToAlarm);
        setMissingData(rec.TreatMissingData || "missing");
        const actions = [...(rec.AlarmActions || []), ...(rec.OKActions || []), ...(rec.InsufficientDataActions || [])];
        const sns = actions.find((a) => a.includes(":sns:"));
        const lambda = actions.find((a) => a.includes(":lambda:"));
        if (sns) setSnsArn(sns);
        if (lambda) setLambdaArn(lambda);
        if (actions.length) setStateTrigger(rec.AlarmActions?.length ? "In alarm" : rec.OKActions?.length ? "OK" : "Insufficient data");
      }
      const t = await api.listTagsForResource(rec.AlarmArn);
      setTags(t.map((x) => ({ key: x.Key, value: x.Value })));
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingName]);

  const thresholdNum = Number(threshold);
  const canSubmit = !!name && (dataSource === "Alarms" ? compositeAlarms.length > 0
    : !!namespace && !!metricName && (thresholdType === "Static" ? threshold !== "" : Number(anomalyStdDevs) > 0));

  const alarmOptions = [...(alarmsList.data?.MetricAlarms || []), ...(alarmsList.data?.CompositeAlarms || [])]
    .filter((a) => a.AlarmName !== name).map((a) => ({ label: a.AlarmName, value: a.AlarmName }));

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true); setError(null);
    try {
      const tagList = tags.filter((t) => t.key).map((t) => ({ Key: t.key, Value: t.value }));
      if (dataSource === "Alarms") {
        const rule = compositeAlarms.map((n) => `ALARM("${n}")`).join(` ${compositeOp} `);
        await api.putCompositeAlarm({ AlarmName: name, AlarmDescription: description || undefined, AlarmRule: rule, Tags: tagList });
      } else {
        const actionArns = [snsArn, lambdaArn].filter(Boolean);
        const common = {
          AlarmName: name, AlarmDescription: description || undefined,
          EvaluationPeriods: Number(evalPeriods), DatapointsToAlarm: Number(datapointsToAlarm), TreatMissingData: missingData,
          AlarmActions: stateTrigger === "In alarm" ? actionArns : [],
          OKActions: stateTrigger === "OK" ? actionArns : [],
          InsufficientDataActions: stateTrigger === "Insufficient data" ? actionArns : [],
          Tags: tagList,
        };
        if (thresholdType === "Anomaly detection") {
          await api.putAnomalyDetector({ Namespace: namespace, MetricName: metricName, Stat: statistic });
          await api.putMetricAlarm({
            ...common, ComparisonOperator: anomalyComparison, ThresholdMetricId: "ad1",
            Metrics: [
              { Id: "m1", MetricStat: { Metric: { Namespace: namespace, MetricName: metricName }, Period: Number(period), Stat: statistic }, ReturnData: false },
              { Id: "ad1", Expression: `ANOMALY_DETECTION_BAND(m1, ${Number(anomalyStdDevs)})`, ReturnData: true },
            ],
          });
        } else {
          await api.putMetricAlarm({
            ...common, Namespace: namespace, MetricName: metricName, Statistic: statistic,
            Period: Number(period), ComparisonOperator: comparison, Threshold: thresholdNum,
          });
        }
      }
      notify.success(`Alarm ${name} was created.`);
      navigate("cloudwatch", "alarms", name);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create alarm</Header>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <Tabs tabs={[
          {
            id: "metric", label: "Specify metric and conditions", content: (
              <SpaceBetween size="l">
                <Container header={<Header variant="h2">Data source</Header>}>
                  <FormField label="Data source">
                    <RadioGroup value={dataSource} onChange={({ detail }) => setDataSource(detail.value)}
                      items={["Metrics", "Logs", "Alarms"].map((v) => ({ value: v, label: v }))} ariaLabel="Data source" />
                  </FormField>
                </Container>
                <Container header={<Header variant="h2">Type</Header>}>
                  <FormField label="Type">
                    <RadioGroup value={type} onChange={({ detail }) => setType(detail.value)}
                      items={[{ value: "Classic", label: "Classic" }, { value: "PromQL", label: "PromQL", disabled: true }]} ariaLabel="Type" />
                  </FormField>
                  {type === "PromQL" && <Alert type="info">PromQL alarms aren't simulated in Vyomi; use Classic.</Alert>}
                </Container>
                {dataSource === "Alarms" ? (
                  <Container header={<Header variant="h2">Alarms</Header>}>
                    <SpaceBetween size="l">
                      <FormField label="Alarms to combine"><Multiselect selectedOptions={compositeAlarms.map((n) => ({ label: n, value: n }))} onChange={({ detail }) => setCompositeAlarms(detail.selectedOptions.map((o) => o.value))} options={alarmOptions} ariaLabel="Alarms to combine" placeholder="Choose alarms" /></FormField>
                      <FormField label="Combine using"><RadioGroup value={compositeOp} onChange={({ detail }) => setCompositeOp(detail.value)} items={[{ value: "OR", label: "OR — alarm if any selected alarm is in ALARM" }, { value: "AND", label: "AND — alarm only if every selected alarm is in ALARM" }]} ariaLabel="Combine using" /></FormField>
                    </SpaceBetween>
                  </Container>
                ) : (
                  <>
                    <Container header={<Header variant="h2">Metric</Header>}>
                      {dataSource === "Logs" && <Box padding={{ bottom: "s" }} color="text-body-secondary">Pick the metric namespace a log group's metric filter publishes to.</Box>}
                      <MetricPicker namespace={namespace} setNamespace={setNamespace} metricName={metricName} setMetricName={setMetricName} />
                    </Container>
                    <Container header={<Header variant="h2">Conditions</Header>}>
                      <SpaceBetween size="l">
                        <FormField label="Statistic"><Select selectedOption={{ label: statistic, value: statistic }} onChange={({ detail }) => setStatistic(detail.selectedOption.value)} options={["Average", "Sum", "Minimum", "Maximum", "SampleCount"].map((s) => ({ label: s, value: s }))} ariaLabel="Statistic" /></FormField>
                        <FormField label="Period"><Select selectedOption={PERIOD_OPTIONS.find((p) => p.value === period)} onChange={({ detail }) => setPeriod(detail.selectedOption.value)} options={PERIOD_OPTIONS} ariaLabel="Period" /></FormField>
                        <FormField label="Threshold type">
                          <RadioGroup value={thresholdType} onChange={({ detail }) => setThresholdType(detail.value)}
                            items={[{ value: "Static", label: "Static" }, { value: "Anomaly detection", label: "Anomaly detection" }]} ariaLabel="Threshold type" />
                        </FormField>
                        {thresholdType === "Anomaly detection" ? (
                          <CapabilityContainer id="aws.cloudwatch.anomaly-detection" title="Anomaly detection">
                            <SpaceBetween size="l">
                              <FormField label={`Whenever ${metricName || "CPUUtilization"} is...`}>
                                <RadioGroup value={anomalyComparison} onChange={({ detail }) => setAnomalyComparison(detail.value)}
                                  items={[
                                    { value: "LessThanLowerOrGreaterThanUpperThreshold", label: "Outside of the band" },
                                    { value: "GreaterThanUpperThreshold", label: "Greater than the band" },
                                    { value: "LessThanLowerThreshold", label: "Lower than the band" },
                                  ]} ariaLabel="Anomaly comparison operator" />
                              </FormField>
                              <FormField label="Anomaly detection threshold" description="Number of standard deviations the band spans around the metric's trained mean.">
                                <Input type="number" value={anomalyStdDevs} onChange={({ detail }) => setAnomalyStdDevs(detail.value)} ariaLabel="Anomaly detection threshold" />
                              </FormField>
                              <FormField label="Datapoints to alarm" description="M out of N datapoints must fall outside the band.">
                                <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                                  <Input type="number" value={String(datapointsToAlarm)} onChange={({ detail }) => setDatapointsToAlarm(Math.max(1, Number(detail.value) || 1))} ariaLabel="Datapoints to alarm" />
                                  <Box>out of</Box>
                                  <Input type="number" value={String(evalPeriods)} onChange={({ detail }) => setEvalPeriods(Math.max(1, Number(detail.value) || 1))} ariaLabel="Evaluation periods" />
                                </SpaceBetween>
                              </FormField>
                            </SpaceBetween>
                          </CapabilityContainer>
                        ) : (
                          <>
                            <FormField label={`Whenever ${metricName || "CPUUtilization"} is...`}>
                              <RadioGroup value={comparison} onChange={({ detail }) => setComparison(detail.value)} items={COMPARISONS} ariaLabel="Comparison operator" />
                            </FormField>
                            <FormField label="than...">
                              <Input type="number" value={threshold} onChange={({ detail }) => setThreshold(detail.value)} ariaLabel="Threshold value" />
                            </FormField>
                            <FormField label="Datapoints to alarm" description="M out of N datapoints must breach the threshold.">
                              <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                                <Input type="number" value={String(datapointsToAlarm)} onChange={({ detail }) => setDatapointsToAlarm(Math.max(1, Number(detail.value) || 1))} ariaLabel="Datapoints to alarm" />
                                <Box>out of</Box>
                                <Input type="number" value={String(evalPeriods)} onChange={({ detail }) => setEvalPeriods(Math.max(1, Number(detail.value) || 1))} ariaLabel="Evaluation periods" />
                              </SpaceBetween>
                            </FormField>
                            <FormField label="Missing data treatment"><Select selectedOption={MISSING_DATA.find((m) => m.value === missingData)} onChange={({ detail }) => setMissingData(detail.selectedOption.value)} options={MISSING_DATA} ariaLabel="Missing data treatment" /></FormField>
                          </>
                        )}
                      </SpaceBetween>
                    </Container>
                  </>
                )}
              </SpaceBetween>
            ),
          },
          {
            id: "actions", label: "Configure actions", content: (
              <SpaceBetween size="l">
                <Container header={<Header variant="h2">Notification</Header>}>
                  <SpaceBetween size="l">
                    <FormField label="Alarm state trigger">
                      <RadioGroup value={stateTrigger} onChange={({ detail }) => setStateTrigger(detail.value)}
                        items={["In alarm", "OK", "Insufficient data"].map((v) => ({ value: v, label: v }))} ariaLabel="Alarm state trigger" />
                    </FormField>
                    <FormField label="Send a notification to the following SNS topic">
                      <RadioGroup value="arn" items={[{ value: "existing", label: "Select an existing SNS topic", disabled: true }, { value: "new", label: "Create new topic", disabled: true }, { value: "arn", label: "Use topic ARN" }]} ariaLabel="Send a notification to the following SNS topic" />
                    </FormField>
                    <FormField label="SNS topic ARN" description="Vyomi really publishes to this topic when the alarm transitions, through the same SNS engine the console's SNS pages use.">
                      <Input value={snsArn} onChange={({ detail }) => setSnsArn(detail.value)} placeholder="arn:aws:sns:us-east-1:123456789012:my-topic" ariaLabel="SNS topic ARN" />
                    </FormField>
                  </SpaceBetween>
                </Container>
                <CapabilityContainer id="aws.cloudwatch.alarms.actions.lambda" title="Lambda action">
                  <FormField label="Lambda function ARN" description="Vyomi really invokes this function when the alarm transitions, through the same Lambda engine the console's Lambda pages use.">
                    <Input value={lambdaArn} onChange={({ detail }) => setLambdaArn(detail.value)} placeholder="arn:aws:lambda:us-east-1:123456789012:function:my-function" ariaLabel="Lambda function ARN" />
                  </FormField>
                </CapabilityContainer>
                <CapabilityContainer id="aws.cloudwatch.alarms.actions.compute" title="Auto Scaling action" />
                <CapabilityContainer id="aws.cloudwatch.alarms.actions.compute" title="EC2 action" />
              </SpaceBetween>
            ),
          },
          {
            id: "details", label: "Add alarm details", content: (
              <SpaceBetween size="l">
                <Container header={<Header variant="h2">Name and description</Header>}>
                  <SpaceBetween size="l">
                    <FormField label="Alarm name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Alarm name" /></FormField>
                    <FormField label="Alarm description - optional"><Textarea value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Alarm description" /></FormField>
                  </SpaceBetween>
                </Container>
                <Container header={<Header variant="h2">Tags</Header>}>
                  <FormField label="Tags" description="Key / Value pairs; up to 50 tags">
                    <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} />
                  </FormField>
                </Container>
              </SpaceBetween>
            ),
          },
          {
            id: "preview", label: "Preview and create", content: (
              <Container header={<Header variant="h2">Preview</Header>}>
                <SpaceBetween size="s">
                  <Box><b>Name:</b> {name || "-"}</Box>
                  {dataSource === "Alarms" ? (
                    <Box><b>Rule:</b> {compositeAlarms.map((n) => `ALARM("${n}")`).join(` ${compositeOp} `) || "-"}</Box>
                  ) : (
                    <>
                      <Box><b>Metric:</b> {namespace && metricName ? `${namespace} / ${metricName}` : "-"}</Box>
                      <Box><b>Condition:</b> {statistic} {metricName || ""} {COMPARISONS.find((c) => c.value === comparison)?.label} {threshold || "-"} for {datapointsToAlarm} out of {evalPeriods} datapoints</Box>
                    </>
                  )}
                </SpaceBetween>
              </Container>
            ),
          },
        ]} />
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => navigate("cloudwatch", "alarms")}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!canSubmit} onClick={submit}>Create alarm</Button>
          </SpaceBetween>
        </Box>
      </SpaceBetween>
    </ContentLayout>
  );
}
