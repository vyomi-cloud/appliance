/* Stage > Canary: a canary release deployment on a stage (REST API v1 canarySettings). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function CanaryTab({ apiId, stage, reload }) {
  const notify = useNotify();
  const cs = stage.canarySettings;
  const [modal, setModal] = useState(null);   // {mode: "create"|"edit", percent, overrides}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const run = async (fn, msg) => { try { await fn(); notify.success(msg); reload(); } catch (e) { notify.error(e); } };
  const parseOverrides = (text) => Object.fromEntries(text.split(",").map((p) => p.trim()).filter(Boolean).map((p) => { const [k, ...v] = p.split("="); return [k.trim(), v.join("=").trim()]; }));
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      if (modal.mode === "create") {
        await api.createDeployment(apiId, { stageName: stage.stageName, description: "Canary deployment",
          canarySettings: { percentTraffic: Number(modal.percent), stageVariableOverrides: parseOverrides(modal.overrides), useStageCache: false } });
        notify.success("Canary created.");
      } else {
        await api.updateStage(apiId, stage.stageName, [
          { op: "replace", path: "/canarySettings/percentTraffic", value: String(modal.percent) },
          ...Object.entries(parseOverrides(modal.overrides)).map(([k, v]) => ({ op: "replace", path: `/canarySettings/stageVariableOverrides/${k}`, value: v })),
        ]);
        notify.success("Canary settings updated.");
      }
      setModal(null); reload();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="apigateway.stage.canary" title="Canary"
      description="Send a percentage of the stage's traffic to a canary deployment before promoting it."
      actions={cs ? (
        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={() => run(() => api.updateStage(apiId, stage.stageName, [{ op: "replace", path: "/deploymentId", value: cs.deploymentId }, { op: "remove", path: "/canarySettings" }]), "Canary promoted to the stage.")}>Promote canary</Button>
          <Button onClick={() => run(() => api.updateStage(apiId, stage.stageName, [{ op: "remove", path: "/canarySettings" }]), "Canary deleted.")}>Delete canary</Button>
          <Button onClick={() => setModal({ mode: "edit", percent: String(cs.percentTraffic), overrides: Object.entries(cs.stageVariableOverrides || {}).map(([k, v]) => `${k}=${v}`).join(", ") })}>Edit</Button>
        </SpaceBetween>
      ) : <Button variant="primary" onClick={() => setModal({ mode: "create", percent: "10", overrides: "" })}>Create canary</Button>}>
      {cs ? (
        <KeyValue columns={3} items={[
          ["Request distribution", <span data-testid="canary-percent">{cs.percentTraffic}% to the canary</span>],
          ["Canary deployment", cs.deploymentId],
          ["Stage deployment", stage.deploymentId],
          ["Use stage cache", cs.useStageCache ? "Yes" : "No"],
          ["Stage variable overrides", Object.entries(cs.stageVariableOverrides || {}).map(([k, v]) => `${k}=${v}`).join(", ") || "None"],
        ]} />
      ) : <Box color="text-body-secondary">This stage has no canary. Create one to deploy the current API configuration to a share of the traffic.</Box>}
      <Modal visible={!!modal} onDismiss={() => setModal(null)} header={modal?.mode === "create" ? "Create canary" : "Edit canary settings"}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setModal(null)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={submit}>{modal?.mode === "create" ? "Create canary" : "Save changes"}</Button></SpaceBetween></Box>}>
        {modal && <SpaceBetween size="m">
          {error && <ErrorAlert error={error} />}
          <FormField label="Percentage of requests directed to the canary" description="0 to 100."><Input type="number" value={modal.percent} onChange={({ detail }) => setModal({ ...modal, percent: detail.value })} ariaLabel="Percent traffic" /></FormField>
          <FormField label="Canary stage variable overrides" description="name=value pairs separated by commas; they replace the stage variable of the same name for canary requests."><Input value={modal.overrides} onChange={({ detail }) => setModal({ ...modal, overrides: detail.value })} ariaLabel="Stage variable overrides" /></FormField>
        </SpaceBetween>}
      </Modal>
    </CapabilityContainer>
  );
}
