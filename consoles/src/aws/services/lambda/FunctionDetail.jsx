import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

const EVENT_KEY = (name) => `vyomi.lambda.testEvents.${name}`;

export default function FunctionDetail({ params, query }) {
  const name = params.name;
  const [tab, setTab] = useState(query.tab || "code");
  const t = useAsync(() => api.getFunction(name), [name]);
  const notify = useNotify();
  const [delModal, setDelModal] = useState(false);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const cfg = t.data.Configuration;
  const source = t.data.Code?.Source || "";

  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={t.reload} iconName="refresh" ariaLabel="Refresh" />
        <Button disabled>Throttle</Button>
        <Button onClick={async () => { try { await navigator.clipboard.writeText(cfg.FunctionArn); notify.success("ARN copied"); } catch { notify.info(cfg.FunctionArn, "ARN"); } }}>Copy ARN</Button>
        <ButtonDropdown items={[{ id: "delete", text: "Delete function" }]} onItemClick={() => setDelModal(true)}>Actions</ButtonDropdown>
      </SpaceBetween>
    }>{name}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Function overview" columns={4} items={[
          ["Description", cfg.Description], ["Last modified", fmtDate(cfg.LastModified)],
          ["Function ARN", cfg.FunctionArn], ["Function URL", t.data._url?.FunctionUrl || "-"],
        ]} />
        <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
          { id: "code", label: "Code", content: <CodeTab name={name} cfg={cfg} source={source} reload={t.reload} /> },
          { id: "test", label: "Test", content: <TestTab name={name} /> },
          { id: "monitor", label: "Monitor", content: <MonitorTab name={name} /> },
          { id: "configuration", label: "Configuration", content: <ConfigurationTab name={name} cfg={cfg} reload={t.reload} /> },
          { id: "aliases", label: "Aliases", content: <AliasesTab name={name} /> },
          { id: "versions", label: "Versions", content: <VersionsTab name={name} reload={t.reload} /> },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={delModal} resourceType="function" names={[name]}
        onDismiss={() => setDelModal(false)}
        onConfirm={async () => { await api.deleteFunction(name); notify.success(`Function "${name}" deleted.`); location.hash = href("lambda", "functions").slice(1); }} />
    </ContentLayout>
  );
}

// ── Code ───────────────────────────────────────────────────────────────────────────────
function CodeTab({ name, cfg, source, reload }) {
  const notify = useNotify();
  const [code, setCode] = useState(source);
  const [busy, setBusy] = useState(false);
  const [editRuntime, setEditRuntime] = useState(false);
  const [handler, setHandler] = useState(cfg.Handler);
  const [addLayer, setAddLayer] = useState(false);
  const layers = useAsync(() => api.listLayers(), []);
  const [layerChoice, setLayerChoice] = useState(null);
  const csc = useAsync(() => api.getFunctionCodeSigningConfig(name), [name, cfg.RevisionId]);
  const cscs = useAsync(() => api.listCodeSigningConfigs(), [name, cfg.RevisionId]);
  const attachedCsc = (cscs.data || []).find((c) => c.CodeSigningConfigArn === csc.data?.CodeSigningConfigArn);
  const enforceSigning = attachedCsc?.CodeSigningPolicies?.UntrustedArtifactOnDeployment === "Enforce";
  const [signingProfile, setSigningProfile] = useState(null);

  const deploy = async () => {
    setBusy(true);
    try {
      await api.updateFunctionCode(name, { Source: code, ...(signingProfile ? { SigningProfileVersionArn: signingProfile.value } : {}) });
      notify.success("Code deployed."); reload();
    }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="lambda.invoke" title="Code source" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <ButtonDropdown items={[{ id: "zip", text: ".zip file" }, { id: "s3", text: "Amazon S3 location" }]}>Upload from</ButtonDropdown>
          <Button href={`#/lambda/functions/${encodeURIComponent(name)}?tab=test`} onFollow={follow}>Test</Button>
          <Button variant="primary" loading={busy} onClick={deploy}>Deploy</Button>
        </SpaceBetween>
      }>
        <FormField label="Code editor" description="Upload from: .zip file / Amazon S3 location">
          <Textarea value={code} onChange={({ detail }) => setCode(detail.value)} rows={12} spellcheck={false} />
        </FormField>
        {enforceSigning && (
          <FormField label="Signing profile version ARN" description={`This function's code signing configuration (${attachedCsc.CodeSigningConfigId}) enforces signature validation — deploys must declare one of its allowed signing profiles or Vyomi rejects them.`}>
            <Select selectedOption={signingProfile} onChange={({ detail }) => setSigningProfile(detail.selectedOption)}
              placeholder="Choose a signing profile"
              options={(attachedCsc.AllowedPublishers?.SigningProfileVersionArns || []).map((p) => ({ value: p, label: p }))} />
          </FormField>
        )}
      </CapabilityContainer>

      <KeyValue title="Code properties" columns={3} items={[
        ["Package size", fmtBytes(cfg.CodeSize)], ["SHA256 hash", cfg.CodeSha256], ["Last modified", fmtDate(cfg.LastModified)],
      ]} />

      <KeyValue title="Runtime settings" actions={<Button onClick={() => setEditRuntime(true)}>Edit</Button>}
        columns={3} items={[["Runtime", cfg.Runtime], ["Handler", cfg.Handler], ["Architecture", (cfg.Architectures || [])[0]]]} />
      <Modal visible={editRuntime} onDismiss={() => setEditRuntime(false)} header="Edit runtime settings"
        footer={<Box float="right"><Button variant="primary" onClick={async () => {
          await api.updateFunctionConfiguration(name, { Handler: handler }); notify.success("Runtime settings updated."); setEditRuntime(false); reload();
        }}>Save</Button></Box>}>
        <FormField label="Handler"><Input value={handler} onChange={({ detail }) => setHandler(detail.value)} ariaLabel="Handler" /></FormField>
      </Modal>

      <Table variant="container"
        header={<Header variant="h2" actions={<Button onClick={() => setAddLayer(true)}>Add a layer</Button>}>Layers</Header>}
        items={(cfg.Layers || []).map((l, i) => ({ ...l, order: i + 1 }))}
        columnDefinitions={[
          { id: "order", header: "Merge order", cell: (l) => l.order },
          { id: "arn", header: "Version ARN", cell: (l) => l.Arn },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No layers</b></Box>} />
      <Modal visible={addLayer} onDismiss={() => setAddLayer(false)} header="Add a layer"
        footer={<Box float="right"><Button variant="primary" disabled={!layerChoice} onClick={async () => {
          await api.updateFunctionConfiguration(name, { Layers: [...(cfg.Layers || []).map((l) => l.Arn), layerChoice.value] });
          notify.success("Layer added."); setAddLayer(false); reload();
        }}>Add</Button></Box>}>
        <FormField label="Layer version ARN">
          <Select selectedOption={layerChoice} onChange={({ detail }) => setLayerChoice(detail.selectedOption)}
            options={(layers.data || []).map((l) => ({ value: l.LatestMatchingVersion.LayerVersionArn, label: `${l.LayerName}:${l.LatestMatchingVersion.Version}` }))}
            placeholder="Choose a layer" />
        </FormField>
      </Modal>
    </SpaceBetween>
  );
}

// ── Test ───────────────────────────────────────────────────────────────────────────────
function loadEvents(name) { try { return JSON.parse(localStorage.getItem(EVENT_KEY(name)) || "{}"); } catch { return {}; } }
function saveEvents(name, events) { try { localStorage.setItem(EVENT_KEY(name), JSON.stringify(events)); } catch { /* storage unavailable */ } }

function TestTab({ name }) {
  const notify = useNotify();
  const [events, setEvents] = useState(() => loadEvents(name));
  const [action, setAction] = useState("Create new event");
  const [invocationType, setInvocationType] = useState("Synchronous");
  const [eventName, setEventName] = useState("");
  const [sharing, setSharing] = useState("Private");
  const [template] = useState("hello-world");
  const [json, setJson] = useState('{"key1": "value1", "key2": "value2", "key3": "value3"}');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const savedNames = Object.keys(events);

  const save = () => {
    if (!eventName.trim()) return;
    const next = { ...events, [eventName]: { json, sharing } };
    setEvents(next); saveEvents(name, next); notify.success(`Saved test event "${eventName}".`);
  };
  const runTest = async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      const payload = JSON.parse(json);
      if (invocationType === "Asynchronous") {
        await api.invoke(name, payload, "Event");
        setResult({ _async: true, message: "Asynchronous invocation accepted (202). The function ran; see Monitor for the outcome, or the configured destination/DLQ." });
      } else {
        const r = await api.invoke(name, payload, "RequestResponse");
        setResult(r);
      }
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="lambda.invoke" title="Test event" actions={
        <SpaceBetween direction="horizontal" size="xs"><Button onClick={save}>Save</Button><Button variant="primary" loading={busy} onClick={runTest}>Test</Button></SpaceBetween>
      }>
        <SpaceBetween size="l">
          <FormField label="Test event action">
            <RadioGroup value={action} onChange={({ detail }) => setAction(detail.value)}
              items={[{ value: "Create new event", label: "Create new event" }, { value: "Edit saved event", label: "Edit saved event", disabled: !savedNames.length }]} />
          </FormField>
          {action === "Edit saved event" && (
            <FormField label="Saved event">
              <Select selectedOption={eventName ? { value: eventName, label: eventName } : null}
                onChange={({ detail }) => { setEventName(detail.selectedOption.value); setJson(events[detail.selectedOption.value]?.json || json); }}
                options={savedNames.map((n) => ({ value: n, label: n }))} placeholder="Choose a saved event" />
            </FormField>
          )}
          <FormField label="Invocation type">
            <RadioGroup value={invocationType} onChange={({ detail }) => setInvocationType(detail.value)}
              items={[{ value: "Synchronous", label: "Synchronous" }, { value: "Asynchronous", label: "Asynchronous" }]} />
          </FormField>
          <FormField label="Event name"><Input value={eventName} onChange={({ detail }) => setEventName(detail.value)} ariaLabel="Event name" /></FormField>
          <FormField label="Event sharing settings">
            <RadioGroup value={sharing} onChange={({ detail }) => setSharing(detail.value)}
              items={[{ value: "Private", label: "Private" }, { value: "Shareable", label: "Shareable" }]} />
          </FormField>
          <FormField label="Template - optional">
            <Select selectedOption={{ value: template, label: template }} options={[{ value: "hello-world", label: "hello-world" }]} disabled />
          </FormField>
          <FormField label="Event JSON"><Textarea value={json} onChange={({ detail }) => setJson(detail.value)} rows={6} /></FormField>
        </SpaceBetween>
      </CapabilityContainer>
      {error && <ErrorAlert error={error} />}
      {result && (
        <Box variant="div">
          <Header variant="h3">{result._async ? "Asynchronous invocation accepted" : `Execution result: ${result.errorType ? "failed" : "succeeded"}`}</Header>
          <Box variant="code"><pre>{result._async ? result.message : JSON.stringify(result, null, 2)}</pre></Box>
        </Box>
      )}
    </SpaceBetween>
  );
}

// ── Monitor ────────────────────────────────────────────────────────────────────────────
function MonitorTab({ name }) {
  const t = useAsync(() => api.recentInvocations(name), [name]);
  const m = t.data?.Metrics || {};
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="lambda.metrics" title="Metrics" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button disabled>View CloudWatch logs</Button><Button disabled>View X-Ray traces</Button><Button disabled>View Lambda Insights</Button>
        </SpaceBetween>
      }>
        <KeyValue columns={3} items={[
          ["Invocations", m.Invocations ?? 0], ["Duration", `${m.AvgDurationMs ?? 0} ms avg`],
          ["Error count and success rate (%)", `${m.ErrorCount ?? 0} errors, ${m.SuccessRatePct ?? 100}% success`],
          ["Throttles", m.Throttles ?? 0], ["Async delivery failures", m.AsyncDeliveryFailures ?? 0], ["Concurrent executions", m.ConcurrentExecutions ?? 0],
        ]} />
      </CapabilityContainer>
      <Table variant="container" header={<Header variant="h2" counter={`(${(t.data?.Invocations || []).length})`}>Recent invocations</Header>}
        items={t.data?.Invocations || []} loading={t.loading} trackBy="RequestId"
        columnDefinitions={[
          { id: "ts", header: "Timestamp", cell: (r) => fmtDate(r.Timestamp) },
          { id: "id", header: "RequestId", cell: (r) => r.RequestId },
          { id: "ls", header: "LogStream", cell: (r) => r.LogStream },
          { id: "d", header: "DurationInMS", cell: (r) => r.DurationInMS },
          { id: "bd", header: "BilledDurationInMS", cell: (r) => r.BilledDurationInMS },
          { id: "ms", header: "MemorySetInMB", cell: (r) => r.MemorySetInMB },
          { id: "mu", header: "MemoryUsedInMB", cell: (r) => r.MemoryUsedInMB },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No invocations yet</b><Box variant="p" color="inherit">Run Test to invoke this function.</Box></Box>} />
    </SpaceBetween>
  );
}

// ── Configuration ──────────────────────────────────────────────────────────────────────
function EditModal({ visible, onDismiss, header, onSave, children }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header={header}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={async () => { setBusy(true); setError(null); try { await onSave(); onDismiss(); } catch (e) { setError(e); } finally { setBusy(false); } }}>Save changes</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">{error && <ErrorAlert error={error} />}{children}</SpaceBetween>
    </Modal>
  );
}

function ConfigurationTab({ name, cfg, reload }) {
  const notify = useNotify();
  const url = useAsync(() => api.getFunctionUrlConfig(name), [name, cfg.RevisionId]);
  const tags = useAsync(() => api.listTags(name), [name, cfg.RevisionId]);
  const triggers = useAsync(() => api.listEventSourceMappings(name), [name, cfg.RevisionId]);
  const policy = useAsync(() => api.getPolicy(name), [name, cfg.RevisionId]);
  const concurrency = useAsync(() => api.recentInvocations(name).then(() => cfg.ReservedConcurrentExecutions), [name, cfg.RevisionId]);
  const eic = useAsync(() => api.getFunctionEventInvokeConfig(name), [name, cfg.RevisionId]);
  const csc = useAsync(() => api.getFunctionCodeSigningConfig(name), [name, cfg.RevisionId]);
  const cscs = useAsync(() => api.listCodeSigningConfigs(), [name, cfg.RevisionId]);

  const [editGeneral, setEditGeneral] = useState(false);
  const [desc, setDesc] = useState(cfg.Description || "");
  const [memory, setMemory] = useState(String(cfg.MemorySize));
  const [storage, setStorage] = useState(String(cfg.EphemeralStorage?.Size || 512));
  const [timeout, setTimeoutS] = useState(String(cfg.Timeout));
  const [snapStart, setSnapStart] = useState(cfg.SnapStart?.ApplyOn || "None");

  const [editUrl, setEditUrl] = useState(false);
  const [urlAuth, setUrlAuth] = useState(url.data?.AuthType || "AWS_IAM");

  const [editEnv, setEditEnv] = useState(false);
  const [envRows, setEnvRows] = useState([]);

  const [manageTags, setManageTags] = useState(false);
  const [tagRows, setTagRows] = useState([]);

  const [editVpc, setEditVpc] = useState(false);
  const [subnets, setSubnets] = useState((cfg.VpcConfig?.SubnetIds || []).join(", "));
  const [sgs, setSgs] = useState((cfg.VpcConfig?.SecurityGroupIds || []).join(", "));

  const [editOps, setEditOps] = useState(false);
  const [logFormat, setLogFormat] = useState(cfg.LoggingConfig?.LogFormat || "Text");
  const [tracing, setTracing] = useState(cfg.TracingConfig?.Mode === "Active");

  const [editConcurrency, setEditConcurrency] = useState(false);
  const [reserved, setReserved] = useState(String(cfg.ReservedConcurrentExecutions ?? ""));
  const [recursive, setRecursive] = useState(cfg.RecursiveLoop || "Terminate");

  const [editAsync, setEditAsync] = useState(false);
  const [maxAge, setMaxAge] = useState(String(eic.data?.MaximumEventAgeInSeconds ?? 21600));
  const [retries, setRetries] = useState(String(eic.data?.MaximumRetryAttempts ?? 2));
  const [dlq, setDlq] = useState(cfg.DeadLetterConfig?.TargetArn || "");
  const [onSuccess, setOnSuccess] = useState(eic.data?.DestinationConfig?.OnSuccess?.Destination || "");
  const [onFailure, setOnFailure] = useState(eic.data?.DestinationConfig?.OnFailure?.Destination || "");

  const [addFs, setAddFs] = useState(false);
  const [apArn, setApArn] = useState(""); const [mount, setMount] = useState("/mnt/efs");

  const [delTrigger, setDelTrigger] = useState(null);

  const [editCsc, setEditCsc] = useState(false);
  const [cscChoice, setCscChoice] = useState(null);
  const attachedCsc = (cscs.data || []).find((c) => c.CodeSigningConfigArn === csc.data?.CodeSigningConfigArn);

  return (
    <SpaceBetween size="l">
      <KeyValue title="General configuration" actions={<Button onClick={() => setEditGeneral(true)}>Edit</Button>}
        columns={3} items={[["Description", cfg.Description], ["Memory", `${cfg.MemorySize} MB`], ["Ephemeral storage", `${cfg.EphemeralStorage?.Size} MB`], ["Timeout", `${cfg.Timeout} sec`], ["SnapStart", cfg.SnapStart?.ApplyOn]]} />
      <EditModal visible={editGeneral} onDismiss={() => setEditGeneral(false)} header="Edit basic settings" onSave={async () => {
        await api.updateFunctionConfiguration(name, { Description: desc, MemorySize: Number(memory), Timeout: Number(timeout), EphemeralStorage: { Size: Number(storage) }, SnapStart: { ApplyOn: snapStart } });
        notify.success("Basic settings updated."); reload();
      }}>
        <FormField label="Description"><Input value={desc} onChange={({ detail }) => setDesc(detail.value)} /></FormField>
        <FormField label="Memory (MB)"><Input type="number" value={memory} onChange={({ detail }) => setMemory(detail.value)} /></FormField>
        <FormField label="Ephemeral storage (MB)"><Input type="number" value={storage} onChange={({ detail }) => setStorage(detail.value)} /></FormField>
        <FormField label="Timeout (sec)"><Input type="number" value={timeout} onChange={({ detail }) => setTimeoutS(detail.value)} /></FormField>
        <FormField label="SnapStart">
          <RadioGroup value={snapStart} onChange={({ detail }) => setSnapStart(detail.value)} items={[{ value: "None", label: "None" }, { value: "PublishedVersions", label: "PublishedVersions" }]} />
        </FormField>
      </EditModal>

      <Table variant="container"
        header={<Header variant="h2" counter={`(${(triggers.data || []).length})`} actions={<Button variant="primary" href={`#/lambda/functions/${encodeURIComponent(name)}/add-trigger`} onFollow={follow}>Add trigger</Button>}>Triggers</Header>}
        items={triggers.data || []} loading={triggers.loading} trackBy="UUID"
        columnDefinitions={[{ id: "trigger", header: "Trigger", cell: (e) => `${e.EventSourceType} — ${e.EventSourceArn || "(generated)"} (${e.State})` }]}
        empty={<Box textAlign="center" color="inherit"><b>No triggers</b></Box>} />
      <DeleteModal visible={!!delTrigger} resourceType="trigger" names={delTrigger ? [delTrigger.EventSourceType] : []}
        onDismiss={() => setDelTrigger(null)}
        onConfirm={async () => { await api.deleteEventSourceMapping(delTrigger.UUID); notify.success("Trigger removed."); setDelTrigger(null); triggers.reload(); }} />

      <KeyValue title="Permissions" items={[["Execution role", cfg.Role], ["Role name", (cfg.Role || "").split("/").pop()]]} />
      <Table variant="container" header={<Header variant="h2">Resource-based policy statements</Header>}
        items={policy.data?.Statement || []}
        columnDefinitions={[
          { id: "sid", header: "Statement ID", cell: (s) => s.Sid }, { id: "p", header: "Principal", cell: (s) => JSON.stringify(s.Principal) },
          { id: "org", header: "Principal organization ID", cell: (s) => s.Condition?.StringEquals?.["aws:PrincipalOrgID"] || "-" },
          { id: "cond", header: "Conditions", cell: (s) => s.Condition ? JSON.stringify(s.Condition) : "-" }, { id: "action", header: "Action", cell: (s) => s.Action },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No resource-based policy statements</b></Box>} />

      <CapabilityContainer id="lambda.destinations" title="Destinations" actions={<Button onClick={() => setEditAsync(true)}>Edit</Button>}>
        <Table variant="embedded"
          items={eic.data ? [{ src: "Async invocation", cond: "On success", type: eic.data.DestinationConfig?.OnSuccess ? "Destination" : "-", dest: eic.data.DestinationConfig?.OnSuccess?.Destination },
                            { src: "Async invocation", cond: "On failure", type: eic.data.DestinationConfig?.OnFailure ? "Destination" : "-", dest: eic.data.DestinationConfig?.OnFailure?.Destination }] : []}
          columnDefinitions={[{ id: "s", header: "Source", cell: (r) => r.src }, { id: "c", header: "Condition", cell: (r) => r.cond },
            { id: "t", header: "Destination type", cell: (r) => r.type }, { id: "d", header: "Destination", cell: (r) => r.dest || "-" }]}
          empty={<Box textAlign="center" color="inherit"><b>No destinations configured</b></Box>} />
      </CapabilityContainer>

      <KeyValue title="Function URL" actions={url.data
          ? <SpaceBetween direction="horizontal" size="xs"><Button onClick={() => setEditUrl(true)}>Edit</Button><Button onClick={async () => { await api.deleteFunctionUrlConfig(name); notify.success("Function URL deleted."); url.reload(); }}>Delete</Button></SpaceBetween>
          : <Button onClick={async () => { await api.createFunctionUrlConfig(name, { AuthType: "AWS_IAM" }); notify.success("Function URL created."); url.reload(); }}>Create function URL</Button>}
        columns={4} items={[["Function URL", url.data?.FunctionUrl], ["Auth type", url.data?.AuthType], ["Invoke mode", url.data?.InvokeMode], ["CORS", url.data?.Cors && Object.keys(url.data.Cors).length ? "Configured" : "-"]]} />
      <EditModal visible={editUrl} onDismiss={() => setEditUrl(false)} header="Edit function URL" onSave={async () => { await api.updateFunctionUrlConfig(name, { AuthType: urlAuth }); notify.success("Function URL updated."); url.reload(); }}>
        <FormField label="Auth type"><RadioGroup value={urlAuth} onChange={({ detail }) => setUrlAuth(detail.value)} items={[{ value: "AWS_IAM", label: "AWS_IAM" }, { value: "NONE", label: "NONE" }]} /></FormField>
      </EditModal>

      <Table variant="container" header={<Header variant="h2" actions={<Button onClick={() => { setEnvRows(Object.entries(cfg.Environment?.Variables || {}).map(([k, v]) => ({ k, v }))); setEditEnv(true); }}>Edit</Button>}>Environment variables</Header>}
        items={Object.entries(cfg.Environment?.Variables || {}).map(([k, v]) => ({ k, v }))}
        columnDefinitions={[{ id: "k", header: "Key", cell: (r) => r.k }, { id: "v", header: "Value", cell: (r) => r.v }]}
        empty={<Box textAlign="center" color="inherit"><b>No environment variables</b></Box>} />
      <EditModal visible={editEnv} onDismiss={() => setEditEnv(false)} header="Edit environment variables"
        onSave={async () => { await api.updateFunctionConfiguration(name, { Environment: { Variables: Object.fromEntries(envRows.filter((r) => r.k).map((r) => [r.k, r.v])) } }); notify.success("Environment variables updated."); reload(); }}>
        <FormField label="Environment variables">
          <Table items={envRows}
            columnDefinitions={[
              { id: "k", header: "Key", cell: (r, i) => <Input value={r.k} onChange={({ detail }) => setEnvRows(envRows.map((x, j) => j === i ? { ...x, k: detail.value } : x))} ariaLabel="Key" /> },
              { id: "v", header: "Value", cell: (r, i) => <Input value={r.v} onChange={({ detail }) => setEnvRows(envRows.map((x, j) => j === i ? { ...x, v: detail.value } : x))} ariaLabel="Value" /> },
            ]}
            footer={<SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => setEnvRows([...envRows, { k: "", v: "" }])}>Add environment variable</Button>
              {envRows.length > 0 && <Button onClick={() => setEnvRows(envRows.slice(0, -1))}>Remove</Button>}
            </SpaceBetween>} />
        </FormField>
      </EditModal>

      <Table variant="container" header={<Header variant="h2" actions={<Button onClick={() => { setTagRows(Object.entries(tags.data || {}).map(([k, v]) => ({ k, v }))); setManageTags(true); }}>Manage tags</Button>}>Tags</Header>}
        items={Object.entries(tags.data || {}).map(([k, v]) => ({ k, v }))}
        columnDefinitions={[{ id: "k", header: "Key", cell: (r) => r.k }, { id: "v", header: "Value", cell: (r) => r.v }]}
        empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>} />
      <EditModal visible={manageTags} onDismiss={() => setManageTags(false)} header="Manage tags" onSave={async () => {
        const next = Object.fromEntries(tagRows.filter((r) => r.k).map((r) => [r.k, r.v]));
        const removed = Object.keys(tags.data || {}).filter((k) => !(k in next));
        if (removed.length) await api.untagResource(name, removed);
        if (Object.keys(next).length) await api.tagResource(name, next);
        notify.success("Tags updated."); tags.reload();
      }}>
        <Table items={tagRows}
          columnDefinitions={[
            { id: "k", header: "Key", cell: (r, i) => <Input value={r.k} onChange={({ detail }) => setTagRows(tagRows.map((x, j) => j === i ? { ...x, k: detail.value } : x))} ariaLabel="Key" /> },
            { id: "v", header: "Value", cell: (r, i) => <Input value={r.v} onChange={({ detail }) => setTagRows(tagRows.map((x, j) => j === i ? { ...x, v: detail.value } : x))} ariaLabel="Value" /> },
          ]}
          footer={<SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => setTagRows([...tagRows, { k: "", v: "" }])}>Add new tag</Button>
            {tagRows.length > 0 && <Button onClick={() => setTagRows(tagRows.slice(0, -1))}>Remove</Button>}
          </SpaceBetween>} />
      </EditModal>

      <CapabilityContainer id="lambda.vpc-filesystems" title="VPC" actions={<Button onClick={() => setEditVpc(true)}>Edit</Button>}>
        <KeyValue columns={3} items={[["VPC", cfg.VpcConfig?.VpcId || "-"], ["Subnets", (cfg.VpcConfig?.SubnetIds || []).join(", ") || "-"], ["Security groups", (cfg.VpcConfig?.SecurityGroupIds || []).join(", ") || "-"]]} />
      </CapabilityContainer>
      <EditModal visible={editVpc} onDismiss={() => setEditVpc(false)} header="Edit VPC" onSave={async () => {
        await api.updateFunctionConfiguration(name, { VpcConfig: subnets.trim() ? { VpcId: "vpc-vyomi", SubnetIds: subnets.split(",").map((s) => s.trim()).filter(Boolean), SecurityGroupIds: sgs.split(",").map((s) => s.trim()).filter(Boolean) } : null });
        notify.success("VPC settings updated."); reload();
      }}>
        <FormField label="Subnets" description="Comma-separated subnet IDs — required together with at least one security group."><Input value={subnets} onChange={({ detail }) => setSubnets(detail.value)} placeholder="subnet-0123456789abcdef0" /></FormField>
        <FormField label="Security groups" description="Comma-separated security group IDs — required together with at least one subnet."><Input value={sgs} onChange={({ detail }) => setSgs(detail.value)} placeholder="sg-0123456789abcdef0" /></FormField>
      </EditModal>

      <NotSimulatedContainer title="RDS databases" feature="Lambda RDS database connectivity helper" />

      <KeyValue title="Monitoring and operations tools" actions={<Button onClick={() => setEditOps(true)}>Edit</Button>}
        columns={3} items={[["CloudWatch Logs", "Enabled"], ["Log format", cfg.LoggingConfig?.LogFormat], ["Log group", `/aws/lambda/${name}`], ["AWS X-Ray", cfg.TracingConfig?.Mode === "Active" ? "Active" : "PassThrough"], ["Enhanced monitoring", "Disabled"]]} />
      <EditModal visible={editOps} onDismiss={() => setEditOps(false)} header="Edit monitoring and operations tools" onSave={async () => {
        await api.updateFunctionConfiguration(name, { LoggingConfig: { LogFormat: logFormat }, TracingConfig: { Mode: tracing ? "Active" : "PassThrough" } });
        notify.success("Monitoring settings updated."); reload();
      }}>
        <FormField label="Log format"><RadioGroup value={logFormat} onChange={({ detail }) => setLogFormat(detail.value)} items={[{ value: "Text", label: "Text" }, { value: "JSON", label: "JSON" }]} /></FormField>
        <FormField label="AWS X-Ray active tracing"><RadioGroup value={tracing ? "on" : "off"} onChange={({ detail }) => setTracing(detail.value === "on")} items={[{ value: "off", label: "PassThrough" }, { value: "on", label: "Active" }]} /></FormField>
      </EditModal>

      <KeyValue title="Concurrency and recursion detection" actions={<Button onClick={() => setEditConcurrency(true)}>Edit</Button>}
        columns={3} items={[["Reserved concurrency", cfg.ReservedConcurrentExecutions ?? "Not reserved"], ["Provisioned concurrency", "None"], ["Recursive loop detection", cfg.RecursiveLoop]]} />
      <EditModal visible={editConcurrency} onDismiss={() => setEditConcurrency(false)} header="Edit concurrency and recursion detection" onSave={async () => {
        if (reserved.trim()) await api.putFunctionConcurrency(name, Number(reserved)); else await api.deleteFunctionConcurrency(name);
        await api.putFunctionRecursionConfig(name, recursive);
        notify.success("Concurrency settings updated."); reload();
      }}>
        <FormField label="Reserved concurrency" description="Leave blank for Not reserved."><Input type="number" value={reserved} onChange={({ detail }) => setReserved(detail.value)} /></FormField>
        <FormField label="Recursive loop detection"><RadioGroup value={recursive} onChange={({ detail }) => setRecursive(detail.value)} items={[{ value: "Allow", label: "Allow" }, { value: "Terminate", label: "Terminate" }]} /></FormField>
      </EditModal>

      <KeyValue title="Asynchronous invocation" actions={<Button onClick={() => setEditAsync(true)}>Edit</Button>}
        columns={3} items={[["Maximum age of event", `${eic.data?.MaximumEventAgeInSeconds ?? 21600} sec`], ["Retry attempts", eic.data?.MaximumRetryAttempts ?? 2], ["Dead-letter queue service", cfg.DeadLetterConfig?.TargetArn ? "Configured" : "None"]]} />
      <EditModal visible={editAsync} onDismiss={() => setEditAsync(false)} header="Edit asynchronous invocation" onSave={async () => {
        await api.putFunctionEventInvokeConfig(name, {
          MaximumEventAgeInSeconds: Number(maxAge), MaximumRetryAttempts: Number(retries),
          DestinationConfig: {
            ...(onSuccess.trim() ? { OnSuccess: { Destination: onSuccess.trim() } } : {}),
            ...(onFailure.trim() ? { OnFailure: { Destination: onFailure.trim() } } : {}),
          },
        });
        await api.updateFunctionConfiguration(name, { DeadLetterConfig: dlq.trim() ? { TargetArn: dlq } : null });
        notify.success("Asynchronous invocation updated."); reload(); eic.reload();
      }}>
        <FormField label="Maximum age of event (sec)"><Input type="number" value={maxAge} onChange={({ detail }) => setMaxAge(detail.value)} /></FormField>
        <FormField label="Retry attempts"><Input type="number" value={retries} onChange={({ detail }) => setRetries(detail.value)} /></FormField>
        <FormField label="On success destination ARN - optional" description="An SQS queue, SNS topic or Lambda function that receives the real result of every successful async (Event) invoke.">
          <Input value={onSuccess} onChange={({ detail }) => setOnSuccess(detail.value)} placeholder="arn:aws:sqs:..." />
        </FormField>
        <FormField label="On failure destination ARN - optional" description="Receives the real error of every failed async (Event) invoke; takes precedence over the dead-letter queue below.">
          <Input value={onFailure} onChange={({ detail }) => setOnFailure(detail.value)} placeholder="arn:aws:sqs:..." />
        </FormField>
        <FormField label="Dead-letter queue ARN - optional"><Input value={dlq} onChange={({ detail }) => setDlq(detail.value)} placeholder="arn:aws:sqs:..." /></FormField>
      </EditModal>

      <CapabilityContainer id="lambda.code-signing" title="Code signing" actions={
        <Button onClick={() => {
          setCscChoice(attachedCsc ? { value: attachedCsc.CodeSigningConfigArn, label: attachedCsc.CodeSigningConfigId } : { value: "", label: "No code signing configuration" });
          setEditCsc(true);
        }}>Edit</Button>
      }>
        <KeyValue items={[
          ["Code signing configuration", attachedCsc ? attachedCsc.CodeSigningConfigId : "Not configured"],
          ...(attachedCsc ? [["Signature validation policy", attachedCsc.CodeSigningPolicies?.UntrustedArtifactOnDeployment]] : []),
        ]} />
      </CapabilityContainer>
      <Modal visible={editCsc} onDismiss={() => setEditCsc(false)} header="Edit code signing configuration"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEditCsc(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            if (cscChoice?.value) await api.putFunctionCodeSigningConfig(name, cscChoice.value);
            else await api.deleteFunctionCodeSigningConfig(name);
            notify.success("Code signing configuration updated."); setEditCsc(false); csc.reload(); reload();
          }}>Save</Button>
        </SpaceBetween></Box>}>
        <FormField label="Code signing configuration">
          <Select selectedOption={cscChoice} onChange={({ detail }) => setCscChoice(detail.selectedOption)}
            options={[{ value: "", label: "No code signing configuration" },
              ...(cscs.data || []).map((c) => ({ value: c.CodeSigningConfigArn, label: c.CodeSigningConfigId }))]} />
        </FormField>
      </Modal>

      <Table variant="container" header={<Header variant="h2" actions={<Button onClick={() => setAddFs(true)}>Add file system</Button>}>File systems</Header>}
        items={cfg.FileSystemConfigs || []}
        columnDefinitions={[{ id: "fs", header: "File system", cell: (f) => f.Arn }, { id: "ap", header: "Access point", cell: (f) => f.Arn }, { id: "mp", header: "Local mount path", cell: (f) => f.LocalMountPath }]}
        empty={<Box textAlign="center" color="inherit"><b>No file systems</b></Box>} />
      <EditModal visible={addFs} onDismiss={() => setAddFs(false)} header="Add file system" onSave={async () => {
        await api.updateFunctionConfiguration(name, { FileSystemConfigs: [...(cfg.FileSystemConfigs || []), { Arn: apArn, LocalMountPath: mount }] });
        notify.success("File system added."); reload();
      }}>
        <FormField label="EFS access point ARN" description="arn:aws:elasticfilesystem:<region>:<account-id>:access-point/fsap-...">
          <Input value={apArn} onChange={({ detail }) => setApArn(detail.value)} placeholder="arn:aws:elasticfilesystem:us-east-1:123456789012:access-point/fsap-0123456789abcdef0" />
        </FormField>
        <FormField label="Local mount path" description="Must be an absolute path under /mnt/."><Input value={mount} onChange={({ detail }) => setMount(detail.value)} /></FormField>
      </EditModal>

      <NotSimulatedContainer title="State machines" feature="Step Functions state machines using this function as a task" />
    </SpaceBetween>
  );
}

// ── Aliases ────────────────────────────────────────────────────────────────────────────
function AliasesTab({ name }) {
  const notify = useNotify();
  const t = useAsync(() => api.listAliases(name), [name]);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  return (
    <>
      <Table variant="container"
        header={<Header variant="h2" counter={`(${(t.data || []).length})`}
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => setDel(true)}>Delete</Button>
            <Button disabled={sel.length !== 1}>Edit</Button>
            <Button variant="primary" href={`#/lambda/functions/${encodeURIComponent(name)}/create-alias`} onFollow={follow}>Create alias</Button>
          </SpaceBetween>}>Aliases</Header>}
        items={t.data || []} loading={t.loading} trackBy="Name" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        columnDefinitions={[
          { id: "n", header: "Name", isRowHeader: true, cell: (a) => a.Name }, { id: "v", header: "Version", cell: (a) => a.FunctionVersion },
          { id: "d", header: "Description", cell: (a) => a.Description || "-" }, { id: "m", header: "Last modified", cell: () => "-" },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No aliases</b></Box>} />
      <DeleteModal visible={del} resourceType="alias" names={sel.map((a) => a.Name)} onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deleteAlias(name, sel[0].Name); notify.success("Alias deleted."); setSel([]); t.reload(); }} />
    </>
  );
}

// ── Versions ───────────────────────────────────────────────────────────────────────────
function VersionsTab({ name, reload }) {
  const notify = useNotify();
  const t = useAsync(() => api.listVersions(name), [name]);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  return (
    <>
      <Table variant="container"
        header={<Header variant="h2" counter={`(${(t.data || []).length})`}
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1 || sel[0]?.Version === "$LATEST"} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={async () => { await api.publishVersion(name); notify.success("New version published."); t.reload(); reload(); }}>Publish new version</Button>
          </SpaceBetween>}>Versions</Header>}
        items={t.data || []} loading={t.loading} trackBy="Version" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        columnDefinitions={[
          { id: "v", header: "Version", isRowHeader: true, cell: (v) => v.Version }, { id: "a", header: "Aliases", cell: () => "-" },
          { id: "d", header: "Description", cell: (v) => v.Description || "-" }, { id: "arn", header: "Function ARN", cell: (v) => v.FunctionArn },
          { id: "m", header: "Last modified", cell: (v) => fmtDate(v.LastModified) },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No versions</b></Box>} />
      <DeleteModal visible={del} resourceType="version" names={sel.map((v) => v.Version)} onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deleteVersion(name, sel[0].Version); notify.success("Version deleted."); setSel([]); t.reload(); }} />
    </>
  );
}
