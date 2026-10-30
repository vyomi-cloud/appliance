/* IAM Dashboard — IAM resource counts + AWS Account (account id/alias/sign-in URL) are
 * real, backed by List* calls. "Security recommendations" and "What's new" are
 * root-account/marketing content Vyomi doesn't model — small honest panels. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Grid from "@cloudscape-design/components/grid";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate, follow } from "../../../common/router.js";
import { ErrorAlert, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

const ACCOUNT_ID = "123456789012";

function ResourceCount({ label, value, href }) {
  return (
    <div>
      <Box variant="awsui-key-label">{label}</Box>
      <Link href={href} onFollow={follow}><Box fontSize="display-l">{value}</Box></Link>
    </div>
  );
}

export default function Dashboard() {
  const notify = useNotify();
  const d = useAsync(() => Promise.all([
    api.listGroups(), api.listUsers(), api.listRoles(), api.listPolicies(),
    api.listSamlProviders(), api.listOidcProviders(), api.listAccountAliases(),
  ]), []);
  const [aliasModal, setAliasModal] = useState(false);
  const [alias, setAlias] = useState("");

  if (d.loading) return <Box padding="l">Loading…</Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const [groups, users, roles, policies, saml, oidc, aliases] = d.data;
  const idpCount = saml.length + oidc.length;
  const signInUrl = aliases[0] ? `https://${aliases[0]}.signin.aws.amazon.com/console` : `https://${ACCOUNT_ID}.signin.aws.amazon.com/console`;

  return (
    <ContentLayout header={<Header variant="h1">IAM Dashboard</Header>}>
      <SpaceBetween size="l">
        <NotSimulatedContainer title="Security recommendations"
          note="Root user has MFA, and Deactivate or delete access keys for root user: Vyomi models IAM users and roles, not a distinct root principal with its own MFA/access-key state to recommend against." />
        <Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}>
          <Container header={<Header variant="h2">IAM resources</Header>}>
            <Grid gridDefinition={[{ colspan: 2.4 }, { colspan: 2.4 }, { colspan: 2.4 }, { colspan: 2.4 }, { colspan: 2.4 }]}>
              <ResourceCount label="User groups" value={groups.length} href="#/iam/groups" />
              <ResourceCount label="Users" value={users.length} href="#/iam/users" />
              <ResourceCount label="Roles" value={roles.length} href="#/iam/roles" />
              <ResourceCount label="Policies" value={policies.length} href="#/iam/policies" />
              <ResourceCount label="Identity providers" value={idpCount} href="#/iam/identity-providers" />
            </Grid>
          </Container>
          <Container header={<Header variant="h2">AWS Account</Header>}>
            <SpaceBetween size="m">
              <div><Box variant="awsui-key-label">Account ID</Box><div>{ACCOUNT_ID}</div></div>
              <div>
                <Box variant="awsui-key-label">Account Alias</Box>
                <div>{aliases[0] || <Link onFollow={(e) => { e.preventDefault(); setAliasModal(true); }}>Create</Link>}</div>
              </div>
              <div><Box variant="awsui-key-label">Sign-in URL for IAM users in this account</Box><div>{signInUrl}</div></div>
            </SpaceBetween>
          </Container>
        </Grid>
        <Grid gridDefinition={[{ colspan: 4 }, { colspan: 4 }, { colspan: 4 }]}>
          <Container header={<Header variant="h2">Quick Links</Header>}>
            <Button onClick={() => navigate("iam", "security-credentials")}>My security credentials</Button>
            <Box variant="small" color="text-body-secondary" margin={{ top: "xs" }}>Manage your access keys, multi-factor authentication (MFA) and other credentials.</Box>
          </Container>
          <Container header={<Header variant="h2">Tools</Header>}>
            <Button onClick={() => navigate("iam", "policy-simulator")}>Policy simulator</Button>
          </Container>
          <NotSimulatedContainer title="What's new" />
        </Grid>
      </SpaceBetween>
      <Modal visible={aliasModal} onDismiss={() => setAliasModal(false)} header="Create account alias"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAliasModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={!alias} onClick={async () => {
            try { await api.createAccountAlias(alias); notify.success(`Account alias "${alias}" created.`); setAliasModal(false); setAlias(""); d.reload(); }
            catch (e) { notify.error(e); }
          }}>Create</Button>
        </SpaceBetween></Box>}>
        <FormField label="Account Alias" constraintText="Up to 63 lowercase letters, digits, and hyphens.">
          <Input value={alias} onChange={({ detail }) => setAlias(detail.value)} ariaLabel="Account Alias" />
        </FormField>
      </Modal>
    </ContentLayout>
  );
}
