/* Visual key-policy editor widgets — real IAM users/roles (ListUsers/ListRoles) for Key
 * administrators / Key users, and a free-form 12-digit account id for Other AWS accounts.
 * Every Add/Remove here rewrites the key policy document and persists it the same way the
 * raw JSON editor does (see policy.js + api.putKeyPolicy). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";

const COLUMNS = [
  { id: "name", header: "Name", cell: (r) => r.Name },
  { id: "path", header: "Path", cell: (r) => r.Path },
  { id: "type", header: "Type", cell: (r) => r.Type },
];

/** This account's IAM users + roles, as {Arn, Name, Path, Type}. */
export function useIamPrincipals() {
  const r = useAsync(() => Promise.all([api.listIamUsers(), api.listIamRoles()]), []);
  const users = (r.data?.[0] || []).map((u) => ({ Arn: u.Arn, Name: u.UserName, Path: u.Path || "/", Type: "User" }));
  const roles = (r.data?.[1] || []).map((x) => ({ Arn: x.Arn, Name: x.RoleName, Path: x.Path || "/", Type: "Role" }));
  return { loading: r.loading, principals: [...users, ...roles] };
}

/** "Key administrators" / "Key users" table: shows the ARNs already granted, resolved
 * against this account's real IAM users/roles; Add picks from the rest, Remove drops them. */
export function PrincipalTable({ title, arns, principals, onChange }) {
  const [sel, setSel] = useState([]);
  const [picking, setPicking] = useState(false);
  const [pickSel, setPickSel] = useState([]);
  const rows = arns.map((arn) => principals.find((p) => p.Arn === arn) || { Arn: arn, Name: arn, Path: "-", Type: "-" });
  const available = principals.filter((p) => !arns.includes(p.Arn));
  return (
    <>
      <Table variant="embedded" items={rows} trackBy="Arn" selectionType="multi" selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h3" counter={`(${rows.length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => { onChange(arns.filter((a) => !sel.some((s) => s.Arn === a))); setSel([]); }}>Remove</Button>
            <Button onClick={() => { setPickSel([]); setPicking(true); }}>Add</Button>
          </SpaceBetween>
        }>{title}</Header>}
        columnDefinitions={COLUMNS}
        empty={<Box textAlign="center" color="inherit">No principals selected</Box>} />
      <Modal visible={picking} onDismiss={() => setPicking(false)} size="large" header={`Add ${title.toLowerCase()}`}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setPicking(false)}>Cancel</Button>
          <Button variant="primary" disabled={!pickSel.length} onClick={() => { onChange([...arns, ...pickSel.map((p) => p.Arn)]); setPicking(false); }}>Add</Button>
        </SpaceBetween></Box>}>
        <Table variant="embedded" items={available} trackBy="Arn" selectionType="multi" selectedItems={pickSel}
          onSelectionChange={({ detail }) => setPickSel(detail.selectedItems)}
          columnDefinitions={COLUMNS}
          empty={<Box textAlign="center" color="inherit">No other IAM users or roles in this account</Box>} />
      </Modal>
    </>
  );
}

/** "Other AWS accounts" table: free-form 12-digit account ids granted cross-account access. */
export function OtherAccountsTable({ accountIds, addLabel, onChange }) {
  const [sel, setSel] = useState([]);
  const [adding, setAdding] = useState(false);
  const [val, setVal] = useState("");
  const [err, setErr] = useState(null);
  const rows = accountIds.map((id) => ({ AccountId: id }));
  return (
    <>
      <Table variant="embedded" items={rows} trackBy="AccountId" selectionType="multi" selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h3" counter={`(${rows.length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => { onChange(accountIds.filter((id) => !sel.some((s) => s.AccountId === id))); setSel([]); }}>Remove</Button>
            <Button onClick={() => { setVal(""); setErr(null); setAdding(true); }}>{addLabel}</Button>
          </SpaceBetween>
        }>Other AWS accounts</Header>}
        columnDefinitions={[{ id: "a", header: "Account ID", cell: (r) => r.AccountId }]}
        empty={<Box textAlign="center" color="inherit">No other AWS accounts</Box>} />
      <Modal visible={adding} onDismiss={() => setAdding(false)} header={addLabel}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAdding(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => {
            if (!/^\d{12}$/.test(val)) { setErr("Enter a 12-digit AWS account ID."); return; }
            if (accountIds.includes(val)) { setErr("This account is already added."); return; }
            onChange([...accountIds, val]); setAdding(false);
          }}>{addLabel}</Button>
        </SpaceBetween></Box>}>
        <FormField label="Account ID" errorText={err}><Input value={val} onChange={({ detail }) => setVal(detail.value)} ariaLabel="Account ID" /></FormField>
      </Modal>
    </>
  );
}
