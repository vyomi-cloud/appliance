/* Shared AWS Organizations UI bits (real data from core/organizations_core.py over the native
 * Organizations wire): the "no organization yet" gate, the organization model hook and the
 * OU/account hierarchy + list views. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import Header from "@cloudscape-design/components/header";
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

/** Loads the organization + its whole tree. data = {org, root, ous, accounts} or {org: null}. */
export function useOrgModel() {
  return useAsync(async () => {
    const org = await api.describeOrganization();
    if (!org) return { org: null };
    const [roots, accounts] = await Promise.all([api.listRoots(), api.listAccounts()]);
    const root = roots[0];
    const ous = [];
    const walk = async (parentId) => { for (const u of await api.listOUsForParent(parentId)) { ous.push({ ...u, ParentId: parentId }); await walk(u.Id); } };
    await walk(root.Id);
    const parentOf = {};
    for (const a of accounts) parentOf[a.Id] = (await api.listParents(a.Id))[0]?.Id;
    return { org, root, ous, accounts: accounts.map((a) => ({ ...a, ParentId: parentOf[a.Id] })) };
  }, []);
}

export function OrgGate({ model, title, children }) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  if (model.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (model.error) return <ErrorAlert error={model.error} />;
  if (!model.data?.org) {
    return (
      <Container header={<Header variant="h2">{title}</Header>}>
        <Box textAlign="center" color="inherit" padding="l">
          <SpaceBetween size="s">
            <b>Your account is not a member of an organization</b>
            <Box variant="p" color="text-body-secondary">Create an organization with all features enabled to manage member accounts, service control policies and centralized root access.</Box>
            <Button variant="primary" loading={busy} onClick={async () => {
              setBusy(true);
              try { await api.createOrganization("ALL"); notify.success("Organization created."); model.reload(); }
              catch (e) { notify.error(e); } finally { setBusy(false); }
            }}>Create organization</Button>
          </SpaceBetween>
        </Box>
      </Container>
    );
  }
  return children(model.data);
}

const ouPath = (m, id) => {
  const parts = [];
  let cur = id;
  while (cur && cur !== m.root.Id) { const u = m.ous.find((x) => x.Id === cur); if (!u) break; parts.unshift(u.Name); cur = u.ParentId; }
  return ["Root", ...parts].join(" / ");
};
export const parentLabel = ouPath;

function TreeNode({ m, parentId, name, extra, depth }) {
  const kids = m.ous.filter((u) => u.ParentId === parentId);
  const accts = m.accounts.filter((a) => a.ParentId === parentId);
  return (
    <div style={{ marginLeft: depth ? 16 : 0 }}>
      <ExpandableSection defaultExpanded headerText={name} variant="footer">
        <SpaceBetween size="xxs">
          {accts.map((a) => (
            <Box key={a.Id} padding={{ left: "l" }} data-org-account={a.Id}>
              {a.Name} <Box variant="small" color="text-body-secondary" display="inline">({a.Id}{a.Id === m.org.MasterAccountId ? ", management account" : ""}{a.Status !== "ACTIVE" ? `, ${a.Status}` : ""}){extra ? " - " + extra(a) : ""}</Box>
            </Box>
          ))}
          {kids.map((u) => <TreeNode key={u.Id} m={m} parentId={u.Id} name={u.Name} extra={extra} depth={depth + 1} />)}
        </SpaceBetween>
      </ExpandableSection>
    </div>
  );
}

/** Hierarchy / List switch over the organization. `extraCols` add List columns; `extra(account)` annotates the tree. */
export function OrgStructure({ m, title, actions, extraCols = [], extra, selection }) {
  const [view, setView] = useState("hierarchy");
  return (
    <Container header={<Header variant="h2" counter={`(${m.accounts.length} accounts)`} actions={<SpaceBetween direction="horizontal" size="xs">
      <SegmentedControl selectedId={view} onChange={({ detail }) => setView(detail.selectedId)} label="View"
        options={[{ id: "hierarchy", text: "Hierarchy" }, { id: "list", text: "List" }]} />{actions}</SpaceBetween>}>{title}</Header>}>
      {view === "hierarchy"
        ? <TreeNode m={m} parentId={m.root.Id} name={`Root (${m.root.Id})`} extra={extra} depth={0} />
        : <Table variant="embedded" items={m.accounts} trackBy="Id" {...(selection || {})}
            columnDefinitions={[
              { id: "name", header: "Account name", isRowHeader: true, cell: (a) => a.Name },
              { id: "id", header: "Account ID", cell: (a) => a.Id },
              { id: "email", header: "Email", cell: (a) => a.Email },
              { id: "ou", header: "Parent", cell: (a) => ouPath(m, a.ParentId) },
              { id: "status", header: "Status", cell: (a) => a.Status },
              { id: "joined", header: "Joined", cell: (a) => fmtDate(a.JoinedTimestamp) },
              ...extraCols,
            ]}
            empty={<Box textAlign="center"><b>No accounts</b></Box>} />}
    </Container>
  );
}
