/* Service landing page — shown before the account has any customer managed keys.
 * Purely informational (no backend needed), like the real console's marketing page. */
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import { navigate } from "../../../common/router.js";

const SECTIONS = [
  ["How it works", "AWS Key Management Service (KMS) lets you create, manage, and control cryptographic keys used to protect your data. Vyomi backs Encrypt, Decrypt, GenerateDataKey, Sign, Verify, and MAC operations with a real, key-separated, tamper-detected engine."],
  ["Benefits and features", "Centralized key management, automatic and on-demand key rotation, key policies, aliases, and symmetric and asymmetric key types — all over the same TrentService wire a real AWS SDK or CLI speaks."],
  ["Related tools and services", "Use keys created here to encrypt data in other Vyomi services, or call Encrypt/Decrypt directly from the native KMS API."],
  ["Pricing", "Vyomi doesn't bill for KMS usage."],
  ["Getting started", "Create a customer managed key, or let a Vyomi service provision its own AWS managed key (aws/<service>) the first time it needs one."],
  ["More resources", "See the Customer managed keys and AWS managed keys pages in the left navigation."],
];

export default function Landing() {
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button variant="primary" onClick={() => navigate("kms", "create-key")}>Create a key</Button>}>AWS Key Management Service</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Get started now</Header>}>
          <SpaceBetween size="s">
            <Box>Create a key to start encrypting data, or generate a data key for envelope encryption.</Box>
            <Button variant="primary" onClick={() => navigate("kms", "create-key")}>Create a key</Button>
          </SpaceBetween>
        </Container>
        {SECTIONS.map(([title, body]) => (
          <Container key={title} header={<Header variant="h2">{title}</Header>}><Box>{body}</Box></Container>
        ))}
      </SpaceBetween>
    </ContentLayout>
  );
}
