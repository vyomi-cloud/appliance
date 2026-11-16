/* Vyomi Nano — in-browser Cedar evaluator: the OSS Cedar Rust core (cedar-policy/cedar, Apache-2.0) compiled to WebAssembly
 * (@cedar-policy/cedar-wasm 4.14.0, 4.4 MB, vendored same-origin). core/cedar_wasm_shim.py calls the global below synchronously.
 *   import { installCedar } from "<base>/cedar/cedar-eval.mjs";
 *   await installCedar("<base>/cedar/");            // fetches cedar_wasm_bg.wasm
 *   globalThis.__vyomi_cedar_eval(JSON.stringify(authorizationCall)) -> JSON string (AuthorizationAnswer)
 * Node/tests: installCedar(null, { wasm: <bytes> }).
 */
import init, { initSync, isAuthorized, checkParsePolicySet } from "./cedar_wasm.js";

export async function installCedar(baseUrl, opts = {}) {
  if (opts.wasm) initSync({ module: opts.wasm });
  else await init({ module_or_path: new URL("cedar_wasm_bg.wasm", baseUrl) });
  globalThis.__vyomi_cedar_eval = (callJson) => {
    const call = JSON.parse(callJson);
    if (call.checkParse) return JSON.stringify(checkParsePolicySet(call.checkParse));
    return JSON.stringify(isAuthorized(call));
  };
  return true;
}
