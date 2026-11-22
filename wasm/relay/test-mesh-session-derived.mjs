// Regression: the relay holds the MASTER key; the portal signs each v1 token with the PER-SESSION key hex(HMAC(master, "session:<id>")).
// v1 (HMAC) is retired (V1_ACCEPTED = false, finding F2): the derivation checks below opt in explicitly ({ v1Accepted: true }) to
// keep the v1 code honest until phase 4 deletes it, and the default must refuse every v1 token, however it was signed.
import crypto from "node:crypto";
import { verify, mint, V1_ACCEPTED } from "./mesh-session.mjs";
let fail = 0; const ok = (n, c) => { console.log((c ? "PASS " : "FAIL ") + n); if (!c) fail++; };
const master = "master-key-for-test";
const sid = "42", now = Math.floor(Date.now() / 1000);
const v1 = { v1Accepted: true };
const derived = crypto.createHmac("sha256", master).update(`session:${sid}`).digest("hex");
const tok = mint(derived, { session_id: sid, tier: "max", session_end: now + 3600, iat: now });
ok("v1 retired: V1_ACCEPTED is false", V1_ACCEPTED === false);
let e0 = ""; try { verify(tok, master); } catch (e) { e0 = e.code; }
ok("default: a correctly derived v1 token is refused (MeshSessionV1Retired)", e0 === "MeshSessionV1Retired");
ok("v1 path: token signed with the per-session key verifies against the master key", verify(tok, master, undefined, v1).session_id === sid);
ok("v1 path: token signed directly with the master key still verifies", verify(mint(master, { session_id: sid, session_end: now + 3600, iat: now }), master, undefined, v1).session_id === sid);
let e1 = ""; try { verify(tok, "some-other-master", undefined, v1); } catch (e) { e1 = e.code; }
ok("v1 path: wrong master key is refused", e1 === "MeshSessionBadSignature");
const forged = mint(crypto.createHmac("sha256", master).update("session:99").digest("hex"), { session_id: sid, session_end: now + 3600, iat: now });
let e2 = ""; try { verify(forged, master, undefined, v1); } catch (e) { e2 = e.code; }
ok("v1 path: token signed with ANOTHER session's key is refused", e2 === "MeshSessionBadSignature");
console.log(fail ? "FAILED" : "all passed"); process.exit(fail ? 1 : 0);
