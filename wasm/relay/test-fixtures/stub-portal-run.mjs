// Run a local stand-in for the portal so you can try vyomi-tunnel by hand (the real endpoint is not built yet).
//   node wasm/relay/test-fixtures/stub-portal-run.mjs            # then follow the printed instructions
// Keys:  VYKAPRO / pro-secret  (Pro: Nano + Mesh)    VYKAFREE / free-secret  (Free: Nano only)    VYKAREVOKED / r  (revoked)
// STUB_CODESPACE=<name>  makes the Pro session name that Codespace (otherwise the tunnel finds your vyomi-mesh-* Codespace itself).
// The stub sends no GitHub token, so `gh` uses your own GitHub sign-in.
import { startStubPortal } from "./stub-portal.mjs";
const port = Number(process.env.STUB_PORT || 8765);
const p = await startStubPortal({ codespace: process.env.STUB_CODESPACE || "", github: null, port, ttl: 900 });
console.log(`stub portal on ${p.url}\n\nIn another terminal:\n  export VYOMI_PORTAL_URL=${p.url}\n  export VYOMI_ACCESS_KEY_ID=VYKAPRO VYOMI_SECRET_ACCESS_KEY=pro-secret     # or VYKAFREE / free-secret\n  vyomi-tunnel list\n\nCtrl-C to stop.`);
