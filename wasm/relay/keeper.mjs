/* Codespace TTL keeper:  vyomi-tunnel keep [--user vscode] [--key <file>] [--interval 240]
 *
 * Holds ONE real ssh session to the Codespace host's sshd (reserved `codespace` target, tunnel architecture 9b) and writes a small
 * line to it every ~interval seconds, because GitHub's idle timer is reset by SSH traffic the client sends, not by our relay's
 * WebSocket traffic.  `ssh` runs the handshake and key auth end to end; the keeper only supplies the schedule, reconnects and stop.
 *
 * Nothing here talks to GitHub or needs `gh`.  It never logs the session token (the ProxyCommand reads it from the environment).
 * It stops at the token's session_end, on abort, or after `maxFailures` consecutive failed connects.
 *
 * Status (for the portal's `keepalive` field): { state: "connecting"|"alive"|"reconnecting"|"stopped", reason?, lastWriteAt, writes, failures }.
 */
import { spawn } from "node:child_process";

const sleep = (ms, signal) => new Promise((res) => {
  const t = setTimeout(res, ms);
  signal?.addEventListener("abort", () => { clearTimeout(t); res(); }, { once: true });
});

/** ssh argv for the host target. `proxy` is the ProxyCommand string, e.g. "vyomi-tunnel connect codespace". */
export function sshArgs({ user = "vscode", key, proxy, target = "codespace" } = {}) {
  const a = ["-T", "-o", "BatchMode=yes", "-o", `ProxyCommand=${proxy}`, "-o", "StrictHostKeyChecking=accept-new",
             "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", "-o", "ConnectTimeout=30"];
  if (key) a.push("-i", key, "-o", "IdentitiesOnly=yes");
  a.push(`${user}@${target}.vyomi`, "cat > /dev/null");               // the remote side just swallows what we send
  return a;
}

/**
 * Run the keeper until stopped.  `spawnFn(cmd, args, opts)` defaults to child_process.spawn (tests inject a fake ssh).
 * Returns { stop(), done: Promise<status>, status() }.
 */
export function keep({
  ssh = "ssh", user, key, proxy, target, intervalMs = 240000, jitter = 0.1, sessionEndMs = Infinity,
  maxFailures = 10, settleMs = 500, backoffMs = [2000, 5000, 15000, 30000, 60000], spawnFn = spawn, now = Date.now, onStatus = () => {}, log = () => {},
  env = process.env,
} = {}) {
  const ac = new AbortController();
  const st = { state: "connecting", lastWriteAt: 0, writes: 0, failures: 0 };
  const set = (patch) => { Object.assign(st, patch); try { onStatus({ ...st }); } catch { /* observer errors never stop the keeper */ } };
  const ended = () => now() >= sessionEndMs;

  const done = (async () => {
    let consecutive = 0;
    while (!ac.signal.aborted && !ended()) {
      set({ state: consecutive ? "reconnecting" : "connecting" });
      const child = spawnFn(ssh, sshArgs({ user, key, proxy, target }), { stdio: ["pipe", "ignore", "pipe"], env });
      let exited = false, errTail = "";
      const exit = new Promise((res) => {
        child.on("exit", (code, sig) => { exited = true; res({ code, sig }); });
        child.on("error", (e) => { exited = true; errTail = e.message; res({ code: -1 }); });
      });
      child.stderr?.on("data", (d) => { errTail = (errTail + d).slice(-300); });
      child.stdin?.on("error", () => { /* the exit handler reports it */ });

      // First write immediately: proves the channel works and counts as activity at once.
      const write = () => {
        if (exited || !child.stdin?.writable) return false;
        child.stdin.write(`vyomi-keepalive ${new Date(now()).toISOString()}\n`);
        set({ state: "alive", lastWriteAt: now(), writes: st.writes + 1 });
        return true;
      };
      let wrote = false;
      const startedAt = now();
      await Promise.race([sleep(settleMs, ac.signal), exit]);             // let ssh authenticate before the first write
      if (!exited && !ac.signal.aborted) wrote = write();
      while (!exited && !ac.signal.aborted && !ended()) {
        const wait = intervalMs * (1 + (Math.random() * 2 - 1) * jitter);
        const cap = Number.isFinite(sessionEndMs) ? Math.max(0, sessionEndMs - now()) : wait;
        await Promise.race([sleep(Math.min(wait, cap), ac.signal), exit]);
        if (!exited && !ac.signal.aborted && !ended()) write();
      }
      if (!exited) { try { child.stdin?.end(); child.kill(); } catch { /* already gone */ } await exit; }
      if (ac.signal.aborted || ended()) break;

      // ssh ended on its own: count a failure only if it never carried a write (a connect/auth failure), then back off.
      consecutive = wrote && now() - startedAt > 5000 ? 0 : consecutive + 1;
      set({ failures: st.failures + 1 });
      log(`keeper: ssh ended (${errTail.trim().split("\n").pop() || "no output"}); failure ${consecutive}`);
      if (consecutive >= maxFailures) { set({ state: "stopped", reason: "too many failed connects" }); return { ...st }; }
      await sleep(backoffMs[Math.min(consecutive - 1, backoffMs.length - 1)], ac.signal);
    }
    set({ state: "stopped", reason: ac.signal.aborted ? "stopped" : "session ended" });
    return { ...st };
  })();

  return { stop: () => ac.abort(), done, status: () => ({ ...st }) };
}
