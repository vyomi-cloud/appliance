/* Create WebSocket API — 5-step wizard matching the native console: API details,
 * Add routes ($connect/$disconnect/$default + custom routes), Attach integrations,
 * Add stages, Review and create. */
import { useState } from "react";
import Wizard from "@cloudscape-design/components/wizard";
import Box from "@cloudscape-design/components/box";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Checkbox from "@cloudscape-design/components/checkbox";
import Table from "@cloudscape-design/components/table";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const PREDEFINED = ["$connect", "$disconnect", "$default"];

function DetailsStep({ s, set }) {
  return (
    <Container header={<Header variant="h2">API details</Header>}>
      <SpaceBetween size="l">
        <FormField label="API name" constraintText="Required"><Input value={s.name} onChange={({ detail }) => set({ name: detail.value })} ariaLabel="API name" /></FormField>
        <FormField label="Route selection expression"><Input value={s.rse} onChange={({ detail }) => set({ rse: detail.value })} ariaLabel="Route selection expression" /></FormField>
      </SpaceBetween>
    </Container>
  );
}

function RoutesStep({ s, set }) {
  const [custom, setCustom] = useState("");
  return (
    <Container header={<Header variant="h2">Routes</Header>}>
      <SpaceBetween size="l">
        <FormField label="Predefined routes">
          <SpaceBetween size="xs">
            {PREDEFINED.map((v) => (
              <Checkbox key={v} checked={s.predefined.includes(v)}
                onChange={({ detail }) => set({ predefined: detail.checked ? [...s.predefined, v] : s.predefined.filter((x) => x !== v) })}>{v}</Checkbox>
            ))}
          </SpaceBetween>
        </FormField>
        <FormField label="Custom routes">
          <SpaceBetween size="s">
            <Table variant="embedded" items={s.custom.map((r) => ({ r }))}
              columnDefinitions={[{ id: "r", header: "Route key", cell: (x) => x.r }]}
              empty={<Box textAlign="center" color="inherit">No custom routes</Box>} />
            <SpaceBetween direction="horizontal" size="xs">
              <Input value={custom} onChange={({ detail }) => setCustom(detail.value)} placeholder="sendMessage" ariaLabel="Custom route key" />
              <Button onClick={() => { if (custom) { set({ custom: [...s.custom, custom] }); setCustom(""); } }}>Add custom route</Button>
            </SpaceBetween>
          </SpaceBetween>
        </FormField>
      </SpaceBetween>
    </Container>
  );
}

function IntegrationsStep({ s, set, fns }) {
  const routes = [...s.predefined, ...s.custom];
  return (
    <Container header={<Header variant="h2">Integrations</Header>}>
      <SpaceBetween size="m">
        {routes.map((r) => (
          <FormField key={r} label={`Lambda function for ${r}`}>
            <Select selectedOption={s.targets[r] ? { value: s.targets[r], label: s.targets[r] } : null}
              placeholder="Choose a Lambda function"
              onChange={({ detail }) => set({ targets: { ...s.targets, [r]: detail.selectedOption.value } })}
              options={(fns.data || []).map((f) => ({ value: f.FunctionName, label: f.FunctionName }))} />
          </FormField>
        ))}
        {!routes.length && <Box color="text-body-secondary">Add routes in the previous step to attach integrations.</Box>}
      </SpaceBetween>
    </Container>
  );
}

function StagesStep({ s, set }) {
  return (
    <Container header={<Header variant="h2">Stages</Header>}>
      <FormField label="Stage name"><Input value={s.stageName} onChange={({ detail }) => set({ stageName: detail.value })} ariaLabel="Stage name" /></FormField>
    </Container>
  );
}

function ReviewStep({ s }) {
  return (
    <Container header={<Header variant="h2">Review</Header>}>
      <SpaceBetween size="s">
        <div><Box variant="awsui-key-label">API name</Box><div>{s.name || "-"}</div></div>
        <div><Box variant="awsui-key-label">Route selection expression</Box><div>{s.rse}</div></div>
        <div><Box variant="awsui-key-label">Routes</Box><div>{[...s.predefined, ...s.custom].join(", ") || "-"}</div></div>
        <div><Box variant="awsui-key-label">Stage</Box><div>{s.stageName}</div></div>
      </SpaceBetween>
    </Container>
  );
}

export default function CreateWebSocketApi() {
  const notify = useNotify();
  const fns = useAsync(() => api.listLambdaFunctions(), []);
  const [idx, setIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [s, setS] = useState({ name: "", rse: "request.body.action", predefined: ["$connect", "$disconnect", "$default"], custom: [], targets: {}, stageName: "production" });
  const set = (patch) => setS((prev) => ({ ...prev, ...patch }));

  const finish = async () => {
    setBusy(true); setError(null);
    try {
      const created = await api.createApiV2({ name: s.name, protocolType: "WEBSOCKET", routeSelectionExpression: s.rse });
      for (const r of [...s.predefined, ...s.custom]) {
        let target = `integrations/_none`;
        const fn = s.targets[r];
        if (fn) {
          const integ = await api.integrationsV2.create(created.apiId, {
            integrationType: "AWS_PROXY", integrationUri: fn, integrationMethod: "ANY",
          });
          target = `integrations/${integ.integrationId}`;
        }
        await api.routesV2.create(created.apiId, { routeKey: r, target: fn ? target : undefined });
      }
      await api.createStageV2(created.apiId, { stageName: s.stageName, autoDeploy: true });
      notify.success(`WebSocket API "${s.name}" created.`);
      navigate("apigateway", "api", created.apiId);
    } catch (e) { setError(e); setIdx(4); } finally { setBusy(false); }
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
        submitButtonText="Create API"
        i18nStrings={{ stepNumberLabel: (n) => `Step ${n}`, collapsedStepsLabel: (n, total) => `Step ${n} of ${total}`, cancelButton: "Cancel", previousButton: "Previous", nextButton: "Next", optional: "optional" }}
        steps={[
          { title: "API details", content: <DetailsStep s={s} set={set} /> },
          { title: "Add routes", content: <RoutesStep s={s} set={set} /> },
          { title: "Attach integrations", content: <IntegrationsStep s={s} set={set} fns={fns} /> },
          { title: "Add stages", content: <StagesStep s={s} set={set} /> },
          { title: "Review and create", content: <ReviewStep s={s} /> },
        ]}
      />
    </Box>
  );
}
