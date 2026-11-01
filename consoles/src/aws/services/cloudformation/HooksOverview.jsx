/* Hooks overview — a dashboard over the real hook registry (ListTypes Type=HOOK /
 * ListHookResults), not static marketing copy: the counts reflect the hooks and
 * invocations this account actually has. */
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Container from "@cloudscape-design/components/container";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import { KeyValue } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { href, follow } from "../../../common/router.js";
import * as api from "./api.js";

export default function HooksOverview() {
  const hooks = useAsync(() => api.listHooks(), []);
  const invocations = useAsync(() => api.listHookResults(), []);
  const enabled = (hooks.data || []).filter((h) => h.Enabled).length;

  return (
    <ContentLayout header={<Header variant="h1">Hooks overview</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Get started" columns={3} actions={<Button variant="primary" href={href("cloudformation", "hooks", "list")} onFollow={follow}>Create a Hook</Button>} items={[
          ["Hooks configured", hooks.loading ? "-" : hooks.data?.length ?? 0],
          ["Enabled hooks", hooks.loading ? "-" : enabled],
          ["Invocations recorded", invocations.loading ? "-" : invocations.data?.length ?? 0],
        ]} />
        <Container header={<Header variant="h2">Use cases</Header>}>
          <Box variant="p">
            Use a hook to enforce a required-tag policy before a stack is created, updated or
            deleted — for example, requiring an <code>Owner</code> or <code>CostCenter</code> tag
            on every stack a team provisions, so untagged infrastructure never lands.
          </Box>
        </Container>
        <Container header={<Header variant="h2">Benefits and features</Header>}>
          <SpaceBetween size="s">
            <Box variant="p">
              Hooks run right before CloudFormation provisions anything (PRE_PROVISION). A Fail-mode
              hook stops the stack operation outright; a Warn-mode hook lets it continue and only
              records the failure, so you can roll out a policy without blocking existing workflows.
            </Box>
            <SpaceBetween direction="horizontal" size="xs">
              <Button href={href("cloudformation", "hooks", "list")} onFollow={follow}>View hooks</Button>
              <Button href={href("cloudformation", "hooks", "invocations")} onFollow={follow}>View invocation history</Button>
            </SpaceBetween>
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
