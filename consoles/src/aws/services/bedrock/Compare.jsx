/* Bedrock > Compare models (capture 008): one card per model with capabilities / supported APIs / features / availability.
 * Rows come from ListFoundationModels + GetFoundationModel (the real operations the page calls). */
import Alert from "@cloudscape-design/components/alert";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";
import { availText } from "../../../common/aiModels.js";

const Sec = ({ t, children }) => <SpaceBetween size="xxs"><Box variant="awsui-key-label">{t}</Box><div>{children}</div></SpaceBetween>;
const Card = ({ m }) => (
  <Container header={<Header variant="h2" description={`by ${m.providerName}`} actions={<SpaceBetween direction="horizontal" size="xs"><Link href="#/bedrock/playground" onFollow={(e) => { e.preventDefault(); location.hash = "#/bedrock/playground"; }}>Open in playground</Link><Link href="#/bedrock/models" onFollow={(e) => { e.preventDefault(); location.hash = "#/bedrock/models"; }}>View model details</Link></SpaceBetween>}>{m.modelName}</Header>}>
    <SpaceBetween size="m">
      <Box color="text-body-secondary">{m.modelId}</Box>
      <Box variant="h5">MODEL CAPABILITIES</Box>
      <ColumnLayout columns={3} variant="text-grid">
        <Sec t="Input modalities">{(m.inputModalities || []).join(", ").toLowerCase()}</Sec>
        <Sec t="Output modalities">{(m.outputModalities || []).join(", ").toLowerCase()}</Sec>
        <Sec t="Streaming">{m.responseStreamingSupported ? "Supported" : "Not supported"}</Sec>
      </ColumnLayout>
      <Box variant="h5">SUPPORTED APIs</Box>
      <SpaceBetween direction="horizontal" size="xxs">{["Converse", "Invoke", ...(m.responseStreamingSupported ? ["ConverseStream"] : [])].map((a) => <Badge key={a}>{a}</Badge>)}</SpaceBetween>
      <Box variant="h5">SUPPORTED BEDROCK FEATURES</Box>
      <SpaceBetween direction="horizontal" size="xxs">{(m.inferenceTypesSupported || []).map((a) => <Badge key={a}>{a === "ON_DEMAND" ? "On-demand" : a}</Badge>)}</SpaceBetween>
      <Box variant="h5">IN-REGION AVAILABILITY</Box>
      <Box>{availText(m.vyomiAvailability, String(m.modelId).replace(/^vyomi\./, ""))}</Box>
    </SpaceBetween>
  </Container>
);
export default function Compare() {
  const t = useAsync(() => api.listModels(), []);
  const ms = (t.data || []).filter((m) => (m.outputModalities || []).includes("TEXT")).slice(0, 6);
  return (
    <ContentLayout header={<Header variant="h1">Compare models</Header>}>
      <SpaceBetween size="m">
        <Alert>Comparison covers the models served by this simulator (Nano: in-browser WebLLM models; Mesh: the open-source pool).</Alert>
        {t.loading ? <Spinner /> : <ColumnLayout columns={Math.min(3, Math.max(1, ms.length))}>{ms.map((m) => <Card key={m.modelId} m={m} />)}</ColumnLayout>}
      </SpaceBetween>
    </ContentLayout>
  );
}
