/* Cloud-agnostic text terminal (xterm-style look; plain React -- the repo ships no xterm bundle). Parses a line, hands kubectl to
 * the adapter (native kubectl when it has one, else the shared emulator over adapter.store) and everything else to adapter.commands.
 * Imperative handle: ref.current.exec("kubectl get pods") echoes the command like a typed line, so the dashboard's quick
 * buttons run real commands visibly. */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { runKubectl } from "./kubectl.js";

const CSS = `
.vk-term{background:#0c0c0c;color:#d4d4d4;font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;border-radius:6px;display:flex;flex-direction:column;min-height:0;height:100%}
.vk-term-bar{padding:6px 12px;background:#1f1f1f;color:#9a9a9a;border-radius:6px 6px 0 0;font-size:11.5px;display:flex;justify-content:space-between}
.vk-term-out{flex:1;overflow:auto;padding:10px 12px;white-space:pre-wrap;word-break:break-word}
.vk-term-out .cmd{color:#7ee787}.vk-term-out .err{color:#ff7b72}.vk-term-out .dim{color:#8b949e}
.vk-term-in{display:flex;gap:8px;padding:8px 12px;border-top:1px solid #2a2a2a}
.vk-term-in span{color:#7ee787}.vk-term-in input{flex:1;background:transparent;border:0;outline:0;color:#f0f0f0;font:inherit}
`;

const Terminal = forwardRef(function Terminal({ adapter, onCommandDone }, ref) {
  const [lines, setLines] = useState(() => [{ t: "dim", s: adapter.banner || "Vyomi cluster terminal. Type 'help' for the commands this terminal understands.\n" }]);
  const [busy, setBusy] = useState(false);
  const [val, setVal] = useState("");
  const hist = useRef([]); const hi = useRef(-1); const end = useRef(null); const inp = useRef(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [lines, busy]);
  const print = (s, t = "") => setLines((l) => [...l, { t, s: String(s).replace(/\n?$/, "\n") }]);

  async function exec(line) {
    line = String(line).replace(/\r/g, "");
    const first = line.split("\n")[0];
    setLines((l) => [...l, { t: "cmd", s: `$ ${first}${line.includes("\n") ? "  # (manifest heredoc)" : ""}\n` }]);
    const cmd = line.trim();
    if (!cmd) return;
    hist.current.push(first); hi.current = -1;
    setBusy(true);
    try {
      if (cmd === "clear") setLines([]);
      else if (cmd === "help") print((adapter.help || []).concat(["kubectl get|delete|apply|create ...   (-n/--namespace, -A, -o wide|json|yaml|name)", "clear                      clear the screen"]).join("\n"));
      else if (cmd.startsWith("kubectl")) {
        const r = adapter.kubectl ? await adapter.kubectl(cmd) : await runKubectl(adapter.store, cmd);
        if (r.logs) print(r.logs, r.exitCode ? "err" : "");
      } else {
        const handled = adapter.commands ? await adapter.commands(cmd, { print: (s) => print(s), error: (s) => print(s, "err"), wait: (ms) => new Promise((r) => setTimeout(r, ms)) }) : false;
        if (!handled) print(`${cmd.split(/\s+/)[0]}: command not found (this terminal understands kubectl and ${adapter.cliName || "the cloud CLI"} backup commands; type 'help')`, "err");
      }
    } catch (e) { print(e.message || String(e), "err"); }
    setBusy(false);
    onCommandDone?.(cmd);
    setTimeout(() => inp.current?.focus(), 0);
  }
  useImperativeHandle(ref, () => ({ exec }));

  const key = (e) => {
    if (e.key === "Enter" && !busy) { const v = val; setVal(""); exec(v); }
    else if (e.key === "ArrowUp" && hist.current.length) { hi.current = Math.min(hist.current.length - 1, hi.current + 1); setVal(hist.current[hist.current.length - 1 - hi.current]); e.preventDefault(); }
    else if (e.key === "ArrowDown") { hi.current = Math.max(-1, hi.current - 1); setVal(hi.current < 0 ? "" : hist.current[hist.current.length - 1 - hi.current]); e.preventDefault(); }
  };
  return (
    <div className="vk-term" data-testid="kube-terminal" onClick={() => inp.current?.focus()}>
      <style>{CSS}</style>
      <div className="vk-term-bar"><span>{adapter.terminalTitle || "terminal"}</span><span>{busy ? "running..." : "ready"}</span></div>
      <div className="vk-term-out" data-testid="kube-terminal-out">
        {lines.map((l, i) => <span key={i} className={l.t}>{l.s}</span>)}
        <div ref={end} />
      </div>
      <div className="vk-term-in"><span>$</span>
        <input ref={inp} aria-label="Terminal input" value={val} disabled={busy} onChange={(e) => setVal(e.target.value)} onKeyDown={key} autoComplete="off" spellCheck={false} placeholder={busy ? "" : "kubectl get pods -n simulation-app"} />
      </div>
    </div>
  );
});
export default Terminal;
