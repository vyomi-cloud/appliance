/* Service home — shown only while the account has no secrets, like the real console;
 * once a secret exists this redirects straight to the Secrets list. Purely informational
 * otherwise (no backend needed). */
import { useEffect } from "react";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { navigate } from "../../../common/router.js";
import * as api from "./api.js";

const SECTIONS = [
  ["How it works", "AWS Secrets Manager stores and retrieves database credentials, API keys, and other secrets. Vyomi backs Create/Get/Put/Update/Delete/Restore and version staging (AWSCURRENT/AWSPREVIOUS) with a real, stateful engine over the same secretsmanager.* wire a real SDK or CLI speaks."],
  ["Benefits and features", "Centralized secret storage, versioned values, automatic and on-demand rotation, resource policies, and tagging — all over the native API."],
  ["Pricing", "Vyomi doesn't bill for Secrets Manager usage."],
  ["Getting started", "Store a new secret to start retrieving it from your applications instead of hard-coding credentials."],
];

export default function Landing() {
  const t = useAsync(() => api.listSecrets(), []);
  useEffect(() => { if (t.data?.length) navigate("secretsmanager", "listsecrets"); }, [t.data]);
  if (t.loading || t.data?.length) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button variant="primary" onClick={() => navigate("secretsmanager", "newsecret")}>Store a new secret</Button>}>AWS Secrets Manager</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Get started</Header>}>
          <SpaceBetween size="s">
            <Box>Store a new secret to protect access to your applications, services, and IT resources.</Box>
            <Button variant="primary" onClick={() => navigate("secretsmanager", "newsecret")}>Store a new secret</Button>
          </SpaceBetween>
        </Container>
        {SECTIONS.map(([title, body]) => (
          <Container key={title} header={<Header variant="h2">{title}</Header>}><Box>{body}</Box></Container>
        ))}
      </SpaceBetween>
    </ContentLayout>
  );
}
