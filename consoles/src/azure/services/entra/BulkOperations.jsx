/* Users | Bulk operations: CSV-driven bulk create and bulk delete over the real Graph users collection. Every row is one
 * real POST /users or DELETE /users/{id}; a failing row is reported and the rest still run (as the portal's bulk jobs do,
 * synchronously here). */
import { useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Menu, MenuItem, MenuList, MenuPopover, MenuTrigger,
  Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

const CREATE_HEADER = "userPrincipalName,displayName,password";
const TEMPLATES = { create: `${CREATE_HEADER}\nada@contoso.onmicrosoft.com,Ada Lovelace,Chang3me!Now`, delete: "userPrincipalName\nada@contoso.onmicrosoft.com" };

function parse(text) {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (!lines.length) return [];
  const head = lines[0].split(",").map((h) => h.trim());
  return lines.slice(1).map((l) => { const c = l.split(","); return Object.fromEntries(head.map((h, i) => [h, (c[i] || "").trim()])); });
}

export default function BulkOperations({ users, onDone }) {
  const notify = useNotify();
  const [mode, setMode] = useState(null);
  const [text, setText] = useState("");
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const open = (m) => { setMode(m); setText(TEMPLATES[m]); setResults(null); };
  const run = async () => {
    setBusy(true);
    const out = [];
    for (const row of parse(text)) {
      const upn = row.userPrincipalName;
      try {
        if (!upn) throw new Error("userPrincipalName is required");
        if (mode === "create") {
          if (!row.displayName || !row.password) throw new Error("displayName and password are required");
          await api.createUser({ userPrincipalName: upn, displayName: row.displayName, mailNickname: upn.split("@")[0], accountEnabled: true,
            passwordProfile: { password: row.password, forceChangePasswordNextSignIn: true }, userType: "Member" });
        } else {
          const u = (users || []).find((x) => x.userPrincipalName?.toLowerCase() === upn.toLowerCase());
          if (!u) throw new Error("no such user");
          await api.deleteUser(u.id);
        }
        out.push({ upn, ok: true });
      } catch (e) { out.push({ upn: upn || "(blank)", ok: false, msg: e.message || String(e) }); }
    }
    setBusy(false); setResults(out);
    const bad = out.filter((r) => !r.ok).length;
    (bad ? notify.error : notify.success)(`${out.length - bad} of ${out.length} succeeded${bad ? `, ${bad} failed` : ""}.`, mode === "create" ? "Bulk create" : "Bulk delete");
    onDone();
  };
  return (
    <>
      <Menu>
        <MenuTrigger disableButtonEnhancement><ToolbarButton>Bulk operations</ToolbarButton></MenuTrigger>
        <MenuPopover><MenuList>
          <MenuItem onClick={() => open("create")}>Bulk create</MenuItem>
          <MenuItem onClick={() => open("delete")}>Bulk delete</MenuItem>
        </MenuList></MenuPopover>
      </Menu>
      <Dialog open={!!mode} onOpenChange={(_, d) => !d.open && setMode(null)}>
        <DialogSurface aria-label="Bulk operation">
          <DialogBody>
            <DialogTitle>{mode === "create" ? "Bulk create users" : "Bulk delete users"}</DialogTitle>
            <DialogContent>
              <p>{mode === "create" ? `One user per line: ${CREATE_HEADER}.` : "One user principal name per line, under the userPrincipalName header."}</p>
              <Textarea value={text} onChange={(_, d) => setText(d.value)} rows={8} style={{ width: "100%" }} aria-label="CSV" />
              {results && (
                <ul aria-label="Results">{results.map((r, i) => <li key={i}>{r.ok ? "✓" : "✗"} {r.upn}{r.msg ? ` — ${r.msg}` : ""}</li>)}</ul>
              )}
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={busy} onClick={run}>{mode === "create" ? "Create" : "Delete"}</Button>
              <Button onClick={() => setMode(null)}>Close</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}
