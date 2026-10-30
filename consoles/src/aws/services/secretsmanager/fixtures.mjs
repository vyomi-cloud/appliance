/* UI-conformance fixtures for Secrets Manager (native secretsmanager.* JSON). See s3/fixtures.mjs. */
const T = (op) => ({ svc: "secretsmanager", target: `secretsmanager.${op}` });

async function ensureSecret(wire, name, value) {
  try { await wire("POST", "/", { ...T("CreateSecret"), body: { Name: name, SecretString: value } }); }
  catch (e) { if (!/ResourceExistsException/.test(e.message)) throw e; }
}

export default {
  "live-secret": async (wire, uniq) => { await ensureSecret(wire, uniq, "v4 live secret"); return uniq; },
  "fixed-secret-edit": async (wire) => { await ensureSecret(wire, "uic-secret-edit", JSON.stringify({ username: "demo", password: "demo" })); },
  "fixed-secret-delete": async (wire) => { await ensureSecret(wire, "uic-secret-delete", "v4 fixed secret"); },
};
