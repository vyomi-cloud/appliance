/* Amazon Bedrock > Overview: the real console's landing (captures B-bedrock 001/002): Quickstart banner, Model catalog +
 * Model spotlight carousel, API keys banner, then Labs / Test / Infer / Tune / Build / Assess sections of link cards. */
import { AI_CHAT } from "../../../common/aiModels.js";
import { useState } from "react";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";
import { LocalModel } from "./Overview.jsx";

const go = (h) => (e) => { e?.preventDefault?.(); location.hash = h; };
const Lnk = ({ to, children }) => <Link href={`#/bedrock/${to}`} onFollow={go(`#/bedrock/${to}`)}>{children}</Link>;
const NewB = () => <Badge color="blue">New</Badge>;
const Item = ({ title, isNew, to, link, children }) => (
  <SpaceBetween size="xs">
    <Box variant="h4">{title} {isNew && <NewB />}</Box>
    <Box color="text-body-secondary">{children}</Box>
    <Lnk to={to}>{link}</Lnk>
  </SpaceBetween>
);
const Section = ({ title, cols = 2, children, desc }) => (
  <Container header={<Header variant="h2" description={desc}>{title}</Header>}>
    <ColumnLayout columns={cols} borders="vertical">{children}</ColumnLayout>
  </Container>
);
// Spotlight = models this simulator actually serves (Nano: WebLLM, Mesh: open-source pool).
const SPOT = AI_CHAT.slice(0, 3).map((m) => ({ name: m.name, text: m.blurb || `${m.name} (${m.vendor}), served locally.` }));

export default function Landing() {
  const [i, setI] = useState(0);
  const models = useAsync(() => api.listModels(), []);
  const n = (models.data || []).length;
  const s = SPOT[i];
  return (
    <ContentLayout header={<Header variant="h1" info={<Link variant="info">Info</Link>}>Overview</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Quickstart</Header>}>
          <SpaceBetween size="s"><Box>Get started with Amazon Bedrock and make your first API call in under 5 minutes. Learn how to generate text, stream responses, or analyze media.</Box><Lnk to="quickstart">View Quickstart</Lnk></SpaceBetween>
        </Container>
        <ColumnLayout columns={2}>
          <Container header={<Header variant="h2">Model catalog</Header>} fitHeight>
            <SpaceBetween size="l"><Box>Amazon Bedrock supports {n > 0 ? `${n} models in this simulator` : "foundation models"} from industry-leading providers (the open Vyomi pool plus provider-named aliases). Select the model best suited for achieving your unique goals.</Box><Lnk to="models">View Model catalog</Lnk></SpaceBetween>
          </Container>
          <Container fitHeight header={<Header variant="h2" actions={<SpaceBetween direction="horizontal" size="xs"><Button iconName="angle-left" variant="icon" ariaLabel="Previous" onClick={() => setI((i + SPOT.length - 1) % SPOT.length)} /><Button iconName="angle-right" variant="icon" ariaLabel="Next" onClick={() => setI((i + 1) % SPOT.length)} /></SpaceBetween>}>Model spotlight</Header>}>
            <SpaceBetween size="s"><Box variant="h3">{s.name}</Box><Box>{s.text}</Box><Link onFollow={go("#/bedrock/playground")} href="#/bedrock/playground">Open in playground</Link>
              <Box color="text-body-secondary" fontSize="body-s">{i + 1} of {SPOT.length}</Box></SpaceBetween>
          </Container>
        </ColumnLayout>
        <Container header={<Header variant="h2">Get started by using API Keys</Header>}>
          <SpaceBetween size="s"><Box>Create an Amazon Bedrock API key in one click using the console and use it to authenticate API requests to Amazon Bedrock. After you create the key, you can integrate it into your setup to be automatically recognized when making requests.</Box><Lnk to="api-keys">View API keys</Lnk></SpaceBetween>
        </Container>
        <Section title="Labs" desc="Labs features are experimental and subject to change. We invite you to try these tools and provide feedback to help us refine them.">
          <Item title="Quotas" isNew to="quotas" link="View Quotas">View approved model quotas for your account across inference types, and learn how to request quota increases.</Item>
          <Item title="Compare models" isNew to="compare-models" link="View Compare models">Compare models including capabilities, supported Bedrock features, and regional availability to choose the best one for your use case.</Item>
        </Section>
        <Section title="Test">
          <Item title="Playground" isNew to="playground" link="Open playground">Experiment with multiple AI models in one place. Fine-tune parameters, compare performance, and find the perfect model for your use case. Test different configurations side-by-side to optimize results before deployment.</Item>
          <Item title="Tokenizer" isNew to="tokenizer" link="View Tokenizer">When you run inference with a foundation model, you're charged for the number of tokens in your input and output. With the tokenizer, you can estimate the number of tokens in your input and refine it as necessary to account for cost, as well as token quotas.</Item>
        </Section>
        <Section title="Infer" cols={3}>
          <Item title="Cross-region inference" to="inference-profiles" link="View cross-region inference">Cross-region inference enables you to seamlessly manage unplanned traffic bursts by utilizing compute across different AWS Regions. With cross-region inference, you can distribute traffic across multiple AWS Regions, enabling higher throughput and enhanced resilience during periods of peak demands.</Item>
          <Item title="Batch inference" to="batch-inference" link="View batch inference">Run model inference on multiple prompts asynchronously to accelerate the processing of large datasets.</Item>
          <Item title="Provisioned Throughput" to="provisioned-throughput" link="View Provisioned Throughput">Use Provisioned Throughput to manage RPM, tokens, and other deployment-based requirements by maintaining predictable performance and a stable environment. By default, you pay as you go for model usage.</Item>
        </Section>
        <Container header={<Header variant="h2">Tune</Header>}>
          <SpaceBetween size="l">
            <SpaceBetween size="xs"><Box variant="h4">Custom models</Box><Box color="text-body-secondary">Customize a model with Distillation or Supervised fine-tuning.</Box><Lnk to="custom-models">View Custom models</Lnk></SpaceBetween>
            <Box variant="h3">Other capabilities</Box>
            <ColumnLayout columns={2} borders="vertical">
              <Item title="Prompt router models" to="prompt-routers" link="View Prompt routers models">Enables you to use a combination of foundation models for your generative AI applications to achieve better performance at lower cost and latency than any single model.</Item>
              <Item title="Marketplace model deployments" to="marketplace-deployments" link="View Marketplace model deployments">View and scale your Marketplace deployments based on usage. Continued adaptation of an existing large language model on large generic corpus to improve the end-task performance of the model.</Item>
            </ColumnLayout>
          </SpaceBetween>
        </Container>
        <Section title="Build" cols={3}>
          <Item title="AgentCore" to="agentcore" link="Go to AgentCore">Bedrock AgentCore provides a comprehensive set of composable capabilities allowing developers to build on their preferred frameworks while addressing specific production challenges.</Item>
          <Item title="Knowledge Bases (KB)" to="knowledge-bases" link="View Knowledge Bases">KBs let you connect your enterprise data to foundation models for retrieval-augmented generation (RAG), with built-in connectors, fully managed ingestion, and agentic retrieval, all without any infrastructure to manage.</Item>
          <Item title="Flows" to="flows" link="View Flows">Connect Prompts, Agents, Knowledge Bases, Guardrails and other AWS services using a node-based visual builder to create, test and deploy user-defined GenAI applications.</Item>
          <Item title="Automated Reasoning" to="automated-reasoning" link="View Automated Reasoning">Create and manage policies that encapsulate the rules of a knowledge domain into a structured format. These policies can be used with Automated Reasoning checks in Amazon Bedrock Guardrails to ensure foundational models content is factually accurate.</Item>
          <Item title="Guardrails" to="guardrails" link="View Guardrails">To prevent inappropriate, offensive, or harmful content, apply filters to ensure that the generated content adheres to the standards or guidelines that you have established.</Item>
          <Item title="Prompt Management" to="prompt-management" link="View Prompt Management">Create, test, and manage prompts and configure models and inference parameters used to run them.</Item>
          <Item title="Data automation" to="data-automation" link="View Data automation">Bedrock Data automation is a new Generative AI (GenAI)-powered multi-modal service that enables developers to transform unstructured content from their enterprise documents, images, video, and audio into structured data needed to power their GenAI and ETL (Extract, Transform, Load) applications.</Item>
        </Section>
        <Container header={<Header variant="h2" description="Evaluate the performance or effectiveness of your models and Knowledge Bases.">Assess</Header>}>
          <ColumnLayout columns={2} borders="vertical">
            <Item title="Model Evaluation" to="evaluations" link="View model evaluations">Model evaluations jobs allow you to evaluate and compare a model's outputs using either automated metrics to human to evaluate the model's output.</Item>
            <Item title="Knowledge Base evaluations" to="evaluations" link="View Knowledge Base evaluations">Evaluate the performance or effectiveness of your knowledge bases. Choose to create an evaluation job that uses Large Language Models (LLMs) to compute metrics (automated) to help you assess performance.</Item>
          </ColumnLayout>
        </Container>
        <LocalModel />
      </SpaceBetween>
    </ContentLayout>
  );
}
