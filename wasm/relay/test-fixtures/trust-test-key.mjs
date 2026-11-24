/* TEST ONLY. `node --import ./test-fixtures/trust-test-key.mjs <relay>.mjs`: the relay process also trusts the PUBLIC test
 * vector key (kid "test-vector", seed 0x00..0x1f, docs/architecture/v4.0/MESH-SESSION-ED25519.md), so tests can sign v2
 * session tokens now that v1 (HMAC) tokens are retired (V1_ACCEPTED = false, finding F2).
 *
 * Why a loader hook and not an env var: TRUSTED_KEYS is pinned in code so that nothing the Codespace owner controls (env,
 * files) can add a key. A test chooses this by how it starts the process; whoever can add node flags to a process already
 * controls it. The seed is public, so a token signed with it means nothing to a process started without this hook.
 */
import { register } from "node:module";

register(new URL("./trust-test-key-hooks.mjs", import.meta.url));
