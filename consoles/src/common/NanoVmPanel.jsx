/* Nano in-browser VMs, shared by the three v4 consoles.
 *
 * On Nano an EC2 instance / Compute Engine instance / Azure VM is a real v86 Linux VM in a SharedWorker (wasm/vm/nano-vm-host.js,
 * window.NanoVM). This file is the React side of that host:
 *   - <NanoVmPanel cloud ref/>   mounts NanoVM.renderConnect (boot state, ssh-via-vyomi-tunnel, xterm shell, "Turn on in-browser VMs")
 *                                into a div React never re-renders into, and repaints it (terminal kept) when this VM changes power state.
 *   - useNanoVmRefresh(reload)   re-run a loader when any VM changes power state (and every few seconds while one is booting), so
 *                                the pending -> running badge flips in place.
 *   - vmShownState(cloud,ref,s)  the state a console should show: the store says "running" the moment the record exists, the VM
 *                                is only running once it booted (VM compute on). Off = the store's state, untouched.
 *   - pendingAttr(pending)       {data-vy-pending} hook the host's CSS animates (pulse / spinner) on any status component.
 * Offline appliance: window.NanoVM is absent and every helper is inert (the exec-based terminal stays the offline path). */
import { useEffect, useRef, useState } from "react";
import Alert from "@cloudscape-design/components/alert";

export const nanoVm = () => (typeof window !== "undefined" && window.NanoVM) || null;
export const nanoVmOn = () => { const n = nanoVm(); try { return !!(n && n.enabled && n.enabled()); } catch { return false; } };
/** True on a Nano page (the host script is loaded even with the flag off). */
export const isNano = () => typeof document !== "undefined" && document.querySelector('meta[name="vyomi-substrate"]')?.content === "nano";

/** The power state to show for a store state. Only rewrites a "running" record while VM compute is on. */
export function vmShownState(cloud, ref, state, map) {
  const n = nanoVm();
  if (!n || !nanoVmOn() || !n.shownPower) return state;
  const running = map?.running || "running";
  if (String(state).toLowerCase() !== String(running).toLowerCase()) return state;
  const p = n.shownPower(cloud, ref);   // running | pending | stopped
  return map?.[p] || state;
}

/** Spread on a status component's wrapper so the host animates it while the VM boots. */
export const pendingAttr = (pending, kind) => (pending && nanoVm() ? { "data-vy-pending": kind || "pulse" } : {});

/** Reload on VM power transitions; poll every 3 s while `active` (a VM is pending) as a safety net. */
export function useNanoVmRefresh(reload, active) {
  const r = useRef(reload); r.current = reload;
  useEffect(() => {
    if (!nanoVm()) return undefined;
    const on = () => r.current && r.current();
    window.addEventListener("nano-vm-power", on);
    return () => window.removeEventListener("nano-vm-power", on);
  }, []);
  useEffect(() => {
    if (!active || !nanoVm()) return undefined;
    const t = setInterval(() => r.current && r.current(), 3000);
    return () => clearInterval(t);
  }, [active]);
}

/** Connect panel for one in-browser VM. `cloud` is aws | gcp | azure; `vmRef` the instance id / name. */
export default function NanoVmPanel({ cloud, vmRef }) {
  const host = useRef(null);
  const [tick, setTick] = useState(0);
  const n = nanoVm();
  useEffect(() => {
    if (!n || !host.current || !vmRef) return undefined;
    const el = host.current;
    el.innerHTML = "";
    n.renderConnect(el, cloud, vmRef);
    return () => { el.innerHTML = ""; };   // the xterm session lives in the host's terminals map and is re-attached next paint
  }, [cloud, vmRef, tick, n]);
  useEffect(() => {
    if (!n) return undefined;
    const id = n.vmId(cloud, vmRef);
    const on = (e) => { if (!e.detail || e.detail.id == null || e.detail.id === id) setTick((x) => x + 1); };
    window.addEventListener("nano-vm-power", on);
    return () => window.removeEventListener("nano-vm-power", on);
  }, [cloud, vmRef, n]);
  if (!n) {
    return <Alert type="info" header="In-browser VMs are not loaded in this view">
      Nano runs instances as real Linux VMs inside your browser tab, but the VM host did not load here. Reload the console; if this persists, the in-browser terminal is unavailable.
    </Alert>;
  }
  return <div data-testid="nano-vm-panel" ref={host} style={{ "--line": "#d5dbdb", "--sub": "#5f6b7a", "--codebg": "rgba(127,127,127,.14)" }} />;
}
