/* Provisioned-capacity auto scaling form (Application Auto Scaling target tracking), shared by Create table and Edit capacity. */
import Checkbox from "@cloudscape-design/components/checkbox";
import FormField from "@cloudscape-design/components/form-field";
import Grid from "@cloudscape-design/components/grid";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { CapabilityContainer } from "../../kit/Capability.jsx";

export const DEFAULT_AS = { read: { enabled: false, min: 1, max: 10, target: 70, scaleIn: true }, write: { enabled: false, min: 1, max: 10, target: 70, scaleIn: true } };

export function validateAs(cfg) {
  for (const k of ["read", "write"]) {
    const c = cfg[k];
    if (!c.enabled) continue;
    if (!(Number(c.min) >= 1) || !(Number(c.max) >= Number(c.min))) return `${k === "read" ? "Read" : "Write"} auto scaling: minimum must be at least 1 and no more than the maximum.`;
    if (!(Number(c.target) > 0 && Number(c.target) <= 90)) return `${k === "read" ? "Read" : "Write"} auto scaling: target utilization must be between 20 and 90 percent.`;
  }
  return null;
}

function One({ kind, value, onChange }) {
  const label = kind === "read" ? "Read" : "Write";
  const set = (patch) => onChange({ ...value, ...patch });
  return (
    <SpaceBetween size="s">
      <Checkbox checked={value.enabled} onChange={({ detail }) => set({ enabled: detail.checked })}>{label} capacity auto scaling</Checkbox>
      {value.enabled && (
        <SpaceBetween size="s">
          <Grid gridDefinition={[{ colspan: 4 }, { colspan: 4 }, { colspan: 4 }]}>
            <FormField label="Minimum capacity units"><Input type="number" value={String(value.min)} onChange={({ detail }) => set({ min: detail.value })} ariaLabel={`${label} minimum capacity units`} /></FormField>
            <FormField label="Maximum capacity units"><Input type="number" value={String(value.max)} onChange={({ detail }) => set({ max: detail.value })} ariaLabel={`${label} maximum capacity units`} /></FormField>
            <FormField label="Target utilization (%)"><Input type="number" value={String(value.target)} onChange={({ detail }) => set({ target: detail.value })} ariaLabel={`${label} target utilization`} /></FormField>
          </Grid>
          <Checkbox checked={value.scaleIn !== false} onChange={({ detail }) => set({ scaleIn: detail.checked })}>Scale in</Checkbox>
        </SpaceBetween>
      )}
    </SpaceBetween>
  );
}

export default function AutoScalingFields({ value, onChange }) {
  return (
    <CapabilityContainer id="dynamodb.autoscaling" title="Auto scaling"
      description="Target-tracking scaling adjusts the table's provisioned capacity from the consumed capacity CloudWatch metrics.">
      <SpaceBetween size="l">
        <One kind="read" value={value.read} onChange={(v) => onChange({ ...value, read: v })} />
        <One kind="write" value={value.write} onChange={(v) => onChange({ ...value, write: v })} />
      </SpaceBetween>
    </CapabilityContainer>
  );
}
