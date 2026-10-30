/* Create user group — single page: name + optional add-users + optional attach-policies. */
import { useState } from "react";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Table from "@cloudscape-design/components/table";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateGroup() {
  const notify = useNotify();
  const data = useAsync(() => Promise.all([api.listUsers(), api.listPolicies()]), []);
  const [name, setName] = useState("");
  const [selUsers, setSelUsers] = useState([]);
  const [selPolicies, setSelPolicies] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  if (data.loading) return <Box padding="l">Loading…</Box>;
  const [users, policies] = data.data;

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createGroup({ GroupName: name });
      for (const u of selUsers) await api.addUserToGroup(name, u.UserName);
      for (const p of selPolicies) await api.attachGroupPolicy(name, p.Arn);
      notify.success(`Group "${name}" created.`);
      navigate("iam", "groups", name);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Box padding={{ top: "l", bottom: "xxl" }}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} header="Couldn't create group" />}
        <Container header={<Header variant="h2">Name the group</Header>}>
          <FormField label="User group name" description="Enter a meaningful name to identify this group." constraintText="Maximum 128 characters. Use alphanumeric and '+=,.@-_' characters.">
            <Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="User group name" />
          </FormField>
        </Container>
        <Container header={<Header variant="h2">Add users to the group - Optional</Header>}>
          <Table variant="embedded" items={users} trackBy="UserName" selectionType="multi" selectedItems={selUsers} onSelectionChange={({ detail }) => setSelUsers(detail.selectedItems)}
            columnDefinitions={[
              { id: "name", header: "User name", cell: (u) => u.UserName }, { id: "groups", header: "Groups", cell: () => "-" },
              { id: "last", header: "Last activity", cell: () => "-" }, { id: "created", header: "Creation time", cell: (u) => fmtDate(u.CreateDate) },
            ]}
            empty={<Box textAlign="center" color="inherit"><b>No users</b></Box>} />
        </Container>
        <Container header={<Header variant="h2">Attach permissions policies - Optional</Header>}>
          <Table variant="embedded" items={policies} trackBy="Arn" selectionType="multi" selectedItems={selPolicies} onSelectionChange={({ detail }) => setSelPolicies(detail.selectedItems)}
            columnDefinitions={[
              { id: "name", header: "Policy name", cell: (p) => p.PolicyName }, { id: "type", header: "Type", cell: () => "Managed" },
              { id: "used", header: "Used as", cell: () => "Permissions policy" }, { id: "desc", header: "Description", cell: (p) => p.Description || "-" },
            ]}
            empty={<Box textAlign="center" color="inherit"><b>No policies</b></Box>} />
        </Container>
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => navigate("iam", "groups")}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!name} onClick={submit}>Create user group</Button>
          </SpaceBetween>
        </Box>
      </SpaceBetween>
    </Box>
  );
}
