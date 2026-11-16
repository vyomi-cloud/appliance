// Test bridge: serves the page-side Cedar evaluator (wasm/cedar/cedar-eval.mjs, the SAME module nano-boot.js / the relay worker install)
// to a Python test over stdin/stdout, one JSON call per line. Python's fake `js.globalThis.__vyomi_cedar_eval` forwards here.
import fs from "node:fs";
import readline from "node:readline";
import { installCedar } from "../../wasm/cedar/cedar-eval.mjs";

await installCedar(null, { wasm: fs.readFileSync(new URL("../../wasm/cedar/cedar_wasm_bg.wasm", import.meta.url)) });
const rl = readline.createInterface({ input: process.stdin });
process.stdout.write("ready\n");
for await (const line of rl) process.stdout.write(globalThis.__vyomi_cedar_eval(line) + "\n");
