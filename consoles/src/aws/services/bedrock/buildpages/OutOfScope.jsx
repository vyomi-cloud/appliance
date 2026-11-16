/* Pages with no honest Vyomi backend: an explicit "Not in scope" panel (reason + what to use instead), never a bare "Coming soon". */
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import Link from "@cloudscape-design/components/link";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { NotSimulated } from "../../../kit/common.jsx";
import { Page } from "../inferTune/Shared.jsx";

const make = (title, description, feature, note, instead) => function OutOfScope() {
  return (
    <Page title={title} description={description}>
      <Container header={<Header variant="h2">{title}</Header>}>
        <NotSimulated feature={feature} outOfScope note={note} />
        <Box textAlign="center" margin={{ top: "s" }}><SpaceBetween size="xxs"><Box variant="awsui-key-label">Use instead</Box>{instead}</SpaceBetween></Box>
      </Container>
    </Page>
  );
};

export const AutomatedReasoning = make("Automated Reasoning", "Formal-logic checks that validate model responses against policies.", "Automated Reasoning",
  "It needs an SMT-solver pipeline that turns natural-language policies into formal rules; CreateGuardrail rejects automatedReasoningPolicyConfig for the same reason.",
  <span>Guardrails <Link href="#/bedrock/guardrails">content, topic, word, PII and contextual-grounding checks</Link>, which are simulated.</span>);

export const DataAutomation = make("Data Automation", "Extract insights from documents, images, audio and video with blueprints and projects.", "Bedrock Data Automation",
  "It runs managed multimodal extraction models. The simulator's local model is text-only, so projects and blueprints could only return invented results.",
  <span>Knowledge bases (<Link href="#/bedrock/knowledge-bases">text ingestion and retrieval</Link>) or Textract-style pipelines you run yourself.</span>);
