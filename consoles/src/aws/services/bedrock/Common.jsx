import StatusIndicator from "@cloudscape-design/components/status-indicator";

export const stat = (s) => (
  <StatusIndicator type={["READY", "ACTIVE", "PREPARED", "AVAILABLE", "COMPLETE", "ENABLED"].includes(s) ? "success" : ["FAILED", "DELETING"].includes(s) ? "error" : s === "NOT_PREPARED" ? "pending" : "in-progress"}>{s}</StatusIndicator>
);
export const NOVA = "amazon.nova-lite-v1:0";
export const TITAN = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0";
export const modelArn = (id) => `arn:aws:bedrock:us-east-1::foundation-model/${id}`;
