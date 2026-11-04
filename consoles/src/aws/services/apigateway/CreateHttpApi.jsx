/* Create HTTP API — 4-step wizard matching the native console: Integrations + API
 * name, Configure routes (optional), Define stages (optional), Review and create. */
import { useState } from "react";
import Wizard from "@cloudscape-design/components/wizard";
import Box from "@cloudscape-design/components/box";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Toggle from "@cloudscape-design/components/toggle";
import Table from "@cloudscape-design/components/table";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const INTEG_TYPES = [{ value: "AWS_PROXY", label: "Lambda" }, { value: "HTTP_PROXY", label: "HTTP" }];
const METHODS = ["ANY", "GET", "POST", "PUT", "DELETE", "PATCH"];

function IntegrationsStep({ s, set, fns }) {
  const [draft, setDraft] = useState({ type: INTEG_TYPES[0], target: "" });
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" counter={`(${s.integrations.length})`}>Integrations</Header>}>
        <SpaceBetween size="m">
          <Table variant="embedded" items={s.integrations}
            columnDefinitions={[
              { id: "t", header: "Integration type", cell: (i) => INTEG_TYPES.find((x) => x.value === i.type)?.label },
              { id: "target", header: "Target", cell: (i) => i.target },
              { id: "v", header: "Version", cell: () => (s.integrations[0]?.type === "AWS_PROXY" ? "2.0" : "1.0") },
            ]}
            empty={<Box textAlign="center" color="inherit">No integrations added yet</Box>} />
          <SpaceBetween direction="horizontal" size="xs">
            <FormField label="Integration type">
              <Select selectedOption={draft.type} onChange={({ detail }) => setDraft({ ...draft, type: detail.selectedOption, target: "" })} options={INTEG_TYPES} />
            </FormField>
            <FormField label="Target">
              {draft.type.value === "AWS_PROXY" ? (
                <Select selectedOption={draft.target ? { value: draft.target, label: draft.target } : null}
                  onChange={({ detail }) => setDraft({ ...draft, target: detail.selectedOption.value })}
                  placeholder="Choose a Lambda function"
                  options={(fns.data || []).map((f) => ({ value: f.FunctionName, label: f.FunctionName }))} />
              ) : (
                <Input value={draft.target} onChange={({ detail }) => setDraft({ ...draft, target: detail.value })} placeholder="https://example.com" ariaLabel="HTTP target URL" />
              )}
            </FormField>
            <Button onClick={() => { if (draft.target) { set({ integrations: [...s.integrations, { type: draft.type.value, target: draft.target }] }); setDraft({ type: INTEG_TYPES[0], target: "" }); } }}>Add integration</Button>
          </SpaceBetween>
        </SpaceBetween>
      </Container>
      <Container header={<Header variant="h2">API name</Header>}>
        <FormField label="API name" constraintText="Required">
          <Input value={s.name} onChange={({ detail }) => set({ name: detail.value })} ariaLabel="API name" />
        </FormField>
      </Container>
    </SpaceBetween>
  );
}

function RoutesStep({ s, set }) {
  const [draft, setDraft] = useState({ method: "ANY", path: "/", integ: 0 });
  return (
    <Container header={<Header variant="h2">Configure routes</Header>}>
      <SpaceBetween size="m">
        <Table variant="embedded" items={s.routes}
          columnDefinitions={[
            { id: "m", header: "Method", cell: (r) => r.method }, { id: "p", header: "Resource path", cell: (r) => r.path },
            { id: "t", header: "Integration target", cell: (r) => s.integrations[r.integ]?.target || "-" },
          ]}
          empty={<Box textAlign="center" color="inherit">No routes configured</Box>} />
        <SpaceBetween direction="horizontal" size="xs">
          <FormField label="Method"><Select selectedOption={{ value: draft.method, label: draft.method }} onChange={({ detail }) => setDraft({ ...draft, method: detail.selectedOption.value })} options={METHODS.map((m) => ({ value: m, label: m }))} /></FormField>
          <FormField label="Resource path"><Input value={draft.path} onChange={({ detail }) => setDraft({ ...draft, path: detail.value })} ariaLabel="Resource path" /></FormField>
          <FormField label="Integration target"><Select selectedOption={s.integrations[draft.integ] ? { value: String(draft.integ), label: s.integrations[draft.integ].target } : null}
            onChange={({ detail }) => setDraft({ ...draft, integ: Number(detail.selectedOption.value) })}
            options={s.integrations.map((i, idx) => ({ value: String(idx), label: i.target }))} /></FormField>
          <Button disabled={!s.integrations.length} onClick={() => set({ routes: [...s.routes, { ...draft }] })}>Add route</Button>
        </SpaceBetween>
      </SpaceBetween>
    </Container>
  );
}

function StagesStep({ s, set }) {
  return (
    <Container header={<Header variant="h2">Configure stages</Header>}>
      <SpaceBetween size="l">
        <FormField label="Stage name"><Input value={s.stageName} onChange={({ detail }) => set({ stageName: detail.value })} ariaLabel="Stage name" /></FormField>
        <FormField label="Auto-deploy"><Toggle checked={s.autoDeploy} onChange={({ detail }) => set({ autoDeploy: detail.checked })}>Auto-deploy</Toggle></FormField>
      </SpaceBetween>
    </Container>
  );
}

function ReviewStep({ s }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Review</Header>}>
        <SpaceBetween size="s">
          <div><Box variant="awsui-key-label">API name</Box><div>{s.name || "-"}</div></div>
          <div><Box variant="awsui-key-label">Integrations</Box><div>{s.integrations.length}</div></div>
          <div><Box variant="awsui-key-label">Routes</Box><div>{s.routes.length}</div></div>
          <div><Box variant="awsui-key-label">Stage</Box><div>{s.stageName} (auto-deploy {s.autoDeploy ? "on" : "off"})</div></div>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );
}

export default function CreateHttpApi() {
  const notify = useNotify();
  const fns = useAsync(() => api.listLambdaFunctions(), []);
  const [idx, setIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [s, setS] = useState({ name: "", integrations: [], routes: [], stageName: "$default", autoDeploy: true });
  const set = (patch) => setS((prev) => ({ ...prev, ...patch }));

  const finish = async () => {
    setBusy(true); setError(null);
    try {
      const created = await api.createApiV2({ name: s.name, protocolType: "HTTP" });
      const integIds = [];
      for (const i of s.integrations) {
        const integ = await api.integrationsV2.create(created.apiId, {
          integrationType: i.type, integrationUri: i.target,
          integrationMethod: "ANY", payloadFormatVersion: i.type === "AWS_PROXY" ? "2.0" : "1.0",
        });
        integIds.push(integ.integrationId);
      }
      for (const r of s.routes) {
        await api.routesV2.create(created.apiId, { routeKey: `${r.method} ${r.path}`, target: `integrations/${integIds[r.integ]}` });
      }
      await api.createStageV2(created.apiId, { stageName: s.stageName, autoDeploy: s.autoDeploy });
      notify.success(`HTTP API "${s.name}" created.`);
      navigate("apigateway", "api", created.apiId);
    } catch (e) { setError(e); setIdx(3); } finally { setBusy(false); }
  };

  return (
    <Box padding={{ top: "l" }}>
      {error && <Box padding={{ horizontal: "l", bottom: "s" }}><ErrorAlert error={error} header="Couldn't create API" /></Box>}
      <Wizard
        activeStepIndex={idx}
        onNavigate={({ detail }) => setIdx(detail.requestedStepIndex)}
        onCancel={() => navigate("apigateway", "apis")}
        onSubmit={finish}
        isLoadingNextStep={busy}
        submitButtonText="Create"
        i18nStrings={{ stepNumberLabel: (n) => `Step ${n}`, collapsedStepsLabel: (n, total) => `Step ${n} of ${total}`, cancelButton: "Cancel", previousButton: "Previous", nextButton: "Next", optional: "optional" }}
        steps={[
          { title: "Create an API", content: <IntegrationsStep s={s} set={set} fns={fns} /> },
          { title: "Configure routes", isOptional: true, content: <RoutesStep s={s} set={set} /> },
          { title: "Define stages", isOptional: true, content: <StagesStep s={s} set={set} /> },
          { title: "Review and create", content: <ReviewStep s={s} /> },
        ]}
      />
    </Box>
  );
}
