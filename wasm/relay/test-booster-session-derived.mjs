// Regression: the relay holds the MASTER key; the portal signs each token with the PER-SESSION key hex(HMAC(master, "session:<id>")).
import crypto from "node:crypto";
import { verify, mint } from "./booster-session.mjs";
let fail = 0; const ok = (n, c) => { console.log((c ? "PASS " : "FAIL ") + n); if (!c) fail++; };
const master = "master-key-for-test";
const sid = "42", now = Math.floor(Date.now() / 1000);
const derived = crypto.createHmac("sha256", master).update(`session:${sid}`).digest("hex");
const tok = mint(derived, { session_id: sid, tier: "max", session_end: now + 3600, iat: now });
ok("token signed with the per-session key verifies against the master key", verify(tok, master).session_id === sid);
ok("token signed directly with the master key still verifies", verify(mint(master, { session_id: sid, session_end: now + 3600, iat: now }), master).session_id === sid);
let e1 = ""; try { verify(tok, "some-other-master"); } catch (e) { e1 = e.code; }
ok("wrong master key is refused", e1 === "BoosterSessionBadSignature");
const forged = mint(crypto.createHmac("sha256", master).update("session:99").digest("hex"), { session_id: sid, session_end: now + 3600, iat: now });
let e2 = ""; try { verify(forged, master); } catch (e) { e2 = e.code; }
ok("token signed with ANOTHER session's key is refused", e2 === "BoosterSessionBadSignature");
console.log(fail ? "FAILED" : "all passed"); process.exit(fail ? 1 : 0);
