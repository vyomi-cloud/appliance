/* "Create new" next to the Server field (also the standalone create-sql-server page):
 * server name + location + authentication. Vyomi models SQL authentication (admin
 * login/password become the server's ARM properties); Entra-only / Entra admin assignment
 * is an honest gap — a server with no SQL login is still created, matching how a real
 * Entra-only server genuinely has none. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Radio, RadioGroup, Select } from "@fluentui/react-components";
import { LOCATIONS } from "../../kit/arm.js";
import { NotSimulated } from "../../kit/common.jsx";

const NAME_RE = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const AUTH = ["Use Microsoft Entra-only authentication", "Use both SQL and Microsoft Entra authentication", "Use SQL authentication"];

export default function CreateSqlServerDialog({ open, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [location, setLocation] = useState("eastus");
  const [auth, setAuth] = useState(AUTH[0]);
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const needsSql = auth === "Use SQL authentication";
  const valid = NAME_RE.test(name) && (!needsSql || (login && password && password === confirm));

  const go = async () => {
    setBusy(true); setError(null);
    try {
      await onCreated({
        name, location,
        properties: needsSql ? { administratorLogin: login, administratorLoginPassword: password, version: "12.0" } : { version: "12.0" },
      });
      setName(""); setLogin(""); setPassword(""); setConfirm(""); onClose();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create SQL Database Server" style={{ maxWidth: 560 }}>
        <DialogBody>
          <DialogTitle>Create SQL Database Server</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <section>
                <h3>Server details</h3>
                <Field label="Server name" required validationMessage={name && !NAME_RE.test(name) ? "Lowercase letters, numbers and hyphens only." : undefined}>
                  <div style={{ display: "flex", alignItems: "center" }}>
                    <Input value={name} onChange={(_, d) => setName(d.value.toLowerCase())} aria-label="Server name" style={{ flex: 1 }} />
                    <span className="vy-muted" style={{ marginLeft: 8, fontSize: 13 }}>.database.windows.net</span>
                  </div>
                </Field>
                <Field label="Location" required style={{ marginTop: 8 }}>
                  <Select value={location} onChange={(_, d) => setLocation(d.value)} aria-label="Location">
                    {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
                  </Select>
                </Field>
              </section>
              <section>
                <h3>Authentication</h3>
                <Field label="Authentication method">
                  <RadioGroup value={auth} onChange={(_, d) => setAuth(d.value)} aria-label="Authentication method">
                    {AUTH.map((a) => <Radio key={a} value={a} label={a} />)}
                  </RadioGroup>
                </Field>
                {auth !== "Use SQL authentication" && (
                  <Field label="Set Microsoft Entra admin" style={{ marginTop: 8 }}>
                    <NotSimulated feature="Microsoft Entra admin assignment for a SQL server" note="The server is still created; it has no SQL administrator login, same as a real Entra-only server." />
                  </Field>
                )}
                {needsSql && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
                    <Field label="Server admin login" required><Input value={login} onChange={(_, d) => setLogin(d.value)} aria-label="Server admin login" /></Field>
                    <Field label="Password" required><Input type="password" value={password} onChange={(_, d) => setPassword(d.value)} aria-label="Password" /></Field>
                    <Field label="Confirm password" required validationMessage={confirm && confirm !== password ? "Passwords don't match." : undefined}>
                      <Input type="password" value={confirm} onChange={(_, d) => setConfirm(d.value)} aria-label="Confirm password" />
                    </Field>
                  </div>
                )}
              </section>
              {error && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 13 }}>{error.code ? `${error.code}: ` : ""}{error.message}</div>}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>{busy ? "Creating..." : "OK"}</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
