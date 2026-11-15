import StatusIndicator from "@cloudscape-design/components/status-indicator";

export const stat = (s) => (
  <StatusIndicator type={["READY", "ACTIVE", "PREPARED", "AVAILABLE", "COMPLETE", "ENABLED"].includes(s) ? "success" : ["FAILED", "DELETING"].includes(s) ? "error" : s === "NOT_PREPARED" ? "pending" : "in-progress"}>{s}</StatusIndicator>
);
import { DEFAULT_CHAT, DEFAULT_EMBED, availText } from "../../../common/aiModels.js";

// The ten mesh-llm models (core/ai_model_catalog.py); Bedrock lists them as vyomi.<id>.
export const NOVA = `vyomi.${DEFAULT_CHAT}`;
export const modelArn = (id) => `arn:aws:bedrock:us-east-1::foundation-model/${id}`;
export const TITAN = modelArn(`vyomi.${DEFAULT_EMBED}`);
/** Model picker option: provider-correct name, model id and the live availability (Needs Mesh (Pro/Max) without the Mesh). */
export const modelOption = (m) => ({ label: m.modelName, description: m.modelId, value: m.modelId, tags: [m.providerName, availText(m.vyomiAvailability, String(m.modelId).replace(/^vyomi\./, ""))] });

/** "Select model" button -> modal with a model Select (the real Playground/Tokenizer pattern). Returns the chosen model option via onChange. */
import { useState as _us } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
export function ModelPicker({ options, value, onChange, loading }) {
  const [open, setOpen] = _us(false);
  const [tmp, setTmp] = _us(null);
  return (
    <>
      {value && <Box variant="p"><b>{value.label}</b><br /><Box variant="small" color="text-body-secondary">{value.description}</Box></Box>}
      <Button variant={value ? "normal" : "primary"} onClick={() => { setTmp(value); setOpen(true); }}>{value ? "Change" : "Select model"}</Button>
      <Modal visible={open} onDismiss={() => setOpen(false)} header="Select model" footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" disabled={!tmp} onClick={() => { onChange(tmp); setOpen(false); }}>Apply</Button></SpaceBetween></Box>}>
        <Select selectedOption={tmp} onChange={({ detail }) => setTmp(detail.selectedOption)} options={options} filteringType="auto" placeholder="Choose a model" statusType={loading ? "loading" : "finished"} ariaLabel="Model" />
      </Modal>
    </>
  );
}
