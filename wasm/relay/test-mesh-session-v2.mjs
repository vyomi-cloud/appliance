// Ed25519 (v2) session tokens at the relay (MESH-SESSION-ED25519.md; MCP-GUARDRAILS finding F2). node wasm/relay/test-mesh-session-v2.mjs
import crypto from "node:crypto";
import { verify, mint, mintV2, TRUSTED_KEYS, V1_ACCEPTED } from "./mesh-session.mjs";
let fail = 0; const ok = (n, c) => { console.log((c ? "PASS " : "FAIL ") + n); if (!c) fail++; };
const code = (f) => { try { f(); return null; } catch (e) { return e.code; } };
const pair = () => { const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
  return { privateKey, pub: publicKey.export({ format: "der", type: "spki" }).subarray(-32).toString("base64url") }; };
const portal = pair(), attacker = pair();
const trusted = { "portal-test": portal.pub };
const now = Math.floor(Date.now() / 1000), claims = { tier: "max", session_id: "42", session_end: now + 3600, iat: now };

ok("pinned constants are frozen / boolean", Object.isFrozen(TRUSTED_KEYS) && typeof V1_ACCEPTED === "boolean");
ok("v2 from the portal key verifies with no HMAC key", verify(mintV2(portal.privateKey, "portal-test", claims), "", now, { trusted }).tier === "max");
ok("v2 signed by another key under the portal's kid is refused", code(() => verify(mintV2(attacker.privateKey, "portal-test", claims), "", now, { trusted })) === "MeshSessionBadSignature");
ok("v2 with an unknown kid is refused", code(() => verify(mintV2(attacker.privateKey, "attacker", claims), "", now, { trusted })) === "MeshSessionUnknownKey");
ok("v2 kid cannot reach Object.prototype", code(() => verify(mintV2(attacker.privateKey, "__proto__", claims), "", now, { trusted })) === "MeshSessionUnknownKey");
const [v, body, sig] = mintV2(portal.privateKey, "portal-test", { ...claims, tier: "pro" }).split(".");
const tampered = Buffer.from(JSON.stringify({ ...JSON.parse(Buffer.from(body, "base64url")), tier: "max" })).toString("base64url");
ok("v2 with an edited payload is refused", code(() => verify(`${v}.${tampered}.${sig}`, "", now, { trusted })) === "MeshSessionBadSignature");
ok("v2 keeps the expiry check", code(() => verify(mintV2(portal.privateKey, "portal-test", { ...claims, session_end: now - 1 }), "", now, { trusted })) === "MeshSessionExpired");
// F2: a Codespace owner holding the per-session HMAC key mints Max for their own session
const master = "relay-master", derived = crypto.createHmac("sha256", master).update("session:42").digest("hex");
const forged = mint(derived, { ...claims, session_end: now + 10 ** 7 });
ok("v1 forged with the leaked per-session key: accepted while V1 is on (F2 open)", verify(forged, master, now, { trusted, v1Accepted: true }).tier === "max");
ok("v1 forged with the leaked per-session key: refused once V1 is retired", code(() => verify(forged, master, now, { trusted, v1Accepted: false })) === "MeshSessionV1Retired");
ok("v1 without a relay key is still KeyMissing", code(() => verify(forged, "", now, { trusted, v1Accepted: true })) === "MeshSessionKeyMissing");
console.log(fail ? "FAILED" : "all passed"); process.exit(fail ? 1 : 0);
