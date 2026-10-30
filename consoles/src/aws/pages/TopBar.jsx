/* The console top bar, laid out like the native one:
 *   [logo] [services ▦] [ Search            [Option+S] ]  ...  [>_] [bell] [?] [gear] [Region ▾] [Account ▾]
 * Every control is real: services drawer, search over the service catalog (⌥S focuses it),
 * notifications (this session's console messages), help panel, visual settings, region. */
import { useEffect, useRef, useState } from "react";
import Icon from "@cloudscape-design/components/icon";
import { SERVICES } from "../services/registry.js";
import { LOGO } from "./logo.js";
import { classicHref } from "../services/registry.js";

const BAR = { background: "#0f141a", color: "#fff", height: 40, display: "flex", alignItems: "center", gap: 4, padding: "0 8px 0 12px",
  fontFamily: '"Open Sans","Helvetica Neue",Roboto,Arial,sans-serif', fontSize: 14, position: "relative" };
const ICONBTN = { background: "none", border: 0, color: "#fff", height: 40, minWidth: 40, display: "inline-flex", alignItems: "center", justifyContent: "center", cursor: "pointer", borderRadius: 4, padding: "0 8px" };
const SEP = { width: 1, height: 20, background: "#414d5c", margin: "0 6px" };
const MENU = { position: "absolute", top: 40, right: 0, minWidth: 240, background: "#192534", color: "#fff", border: "1px solid #414d5c", borderRadius: 8,
  boxShadow: "0 4px 20px rgba(0,0,0,.45)", padding: "8px 0", zIndex: 2000, fontSize: 14 };
const ITEM = { display: "block", width: "100%", textAlign: "left", background: "none", border: 0, color: "#fff", padding: "6px 16px", cursor: "pointer", fontSize: 14, textDecoration: "none" };

function Pop({ open, onClose, children, style }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const on = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    const esc = (e) => e.key === "Escape" && onClose();
    setTimeout(() => document.addEventListener("mousedown", on), 0);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", on); document.removeEventListener("keydown", esc); };
  }, [open]);
  return open ? <div ref={ref} style={{ ...MENU, ...style }}>{children}</div> : null;
}

function Search() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const input = useRef(null);
  useEffect(() => {
    const key = (e) => { if (e.altKey && (e.key === "s" || e.key === "ß" || e.code === "KeyS")) { e.preventDefault(); input.current?.focus(); setOpen(true); } };
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  }, []);
  const t = q.trim().toLowerCase();
  const hits = t ? SERVICES.filter((s) => `${s.title} ${s.description} ${s.id}`.toLowerCase().includes(t)) : [];
  const go = (s) => { location.hash = `/${s.id}`; setQ(""); setOpen(false); input.current?.blur(); };
  return (
    <div style={{ position: "relative", flex: "0 1 520px", marginLeft: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, height: 30, border: "1px solid #8c8c94", borderRadius: 8, padding: "0 10px", background: "#0f141a" }}>
        <Icon name="search" variant="inverted" />
        <input ref={input} value={q} placeholder="Search" aria-label="Search"
          onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
          onKeyDown={(e) => { if (e.key === "Enter" && hits[0]) go(hits[0]); if (e.key === "Escape") { setOpen(false); e.target.blur(); } }}
          style={{ flex: 1, background: "none", border: 0, outline: "none", color: "#fff", fontSize: 14, fontStyle: q ? "normal" : "italic" }} />
        <span style={{ color: "#b6bec9", fontSize: 12, whiteSpace: "nowrap" }}>[Option+S]</span>
      </div>
      <Pop open={open && !!t} onClose={() => setOpen(false)} style={{ left: 0, right: "auto", width: "100%", top: 34 }}>
        <div style={{ padding: "4px 16px 8px", fontWeight: 700 }}>Services</div>
        {hits.length ? hits.map((s) => (
          <button key={s.id} style={{ ...ITEM, padding: "8px 16px" }} onClick={() => go(s)}>
            <div style={{ fontWeight: 700, color: "#539fe5" }}>{s.title}</div>
            <div style={{ fontSize: 12, color: "#b6bec9", marginTop: 2 }}>{s.description}</div>
          </button>
        )) : <div style={{ padding: "6px 16px", color: "#b6bec9" }}>No services match "{q}"</div>}
      </Pop>
    </div>
  );
}

export default function TopBar({ onServices, region, regions, onRegion, mode, density, onMode, onDensity, onHelp, notifications, onNotice }) {
  const [menu, setMenu] = useState(null);
  const toggle = (m) => setMenu((x) => (x === m ? null : m));
  const regionLabel = regions.find(([r]) => r === region)?.[1] || region;
  const unread = notifications.length;
  return (
    <div style={BAR} role="banner">
      <a href="#/" aria-label="vyomi.cloud AWS — Console Home" style={{ display: "inline-flex", alignItems: "center", marginRight: 6 }}>
        <img src={LOGO} alt="vyomi.cloud | AWS" height={26} style={{ display: "block" }} />
      </a>
      <span style={SEP} />
      <button style={ICONBTN} aria-label="Services" title="Services" onClick={onServices}><Icon name="grid-view" variant="inverted" /></button>
      <Search />
      <div style={{ flex: 1 }} />
      <button style={ICONBTN} aria-label="CloudShell" title="CloudShell"
        onClick={() => onNotice("CloudShell isn't simulated in Vyomi. Use your own terminal: every SDK and CLI works against this endpoint.", "CloudShell")}>
        <Icon name="command-prompt" variant="inverted" />
      </button>
      <div style={{ position: "relative" }}>
        <button style={ICONBTN} aria-label="Notifications" title="Notifications" onClick={() => toggle("bell")}>
          <Icon name="notification" variant="inverted" />
          {unread > 0 && <span style={{ position: "absolute", top: 6, right: 4, background: "#d91515", color: "#fff", borderRadius: 8, fontSize: 10, minWidth: 16, height: 16, lineHeight: "16px", textAlign: "center", padding: "0 3px" }}>{unread}</span>}
        </button>
        <Pop open={menu === "bell"} onClose={() => setMenu(null)} style={{ width: 360 }}>
          <div style={{ padding: "4px 16px 8px", fontWeight: 700 }}>Notifications</div>
          {notifications.length ? notifications.slice(0, 10).map((n) => (
            <div key={n.id} style={{ padding: "8px 16px", borderTop: "1px solid #414d5c" }}>
              <div style={{ fontWeight: 700, color: n.type === "error" ? "#ff7a7a" : n.type === "success" ? "#29ad32" : "#539fe5" }}>{n.header || ({ success: "Success", error: "Error", info: "Info" }[n.type])}</div>
              <div style={{ fontSize: 13 }}>{n.content}</div>
              <div style={{ fontSize: 11, color: "#b6bec9", marginTop: 2 }}>{n.at.toLocaleTimeString()}</div>
            </div>
          )) : <div style={{ padding: "6px 16px", color: "#b6bec9" }}>No notifications in this session.</div>}
        </Pop>
      </div>
      <button style={ICONBTN} aria-label="Help" title="Help" onClick={onHelp}><Icon name="support" variant="inverted" /></button>
      <div style={{ position: "relative" }}>
        <button style={ICONBTN} aria-label="Settings" title="Settings" onClick={() => toggle("gear")}><Icon name="settings" variant="inverted" /></button>
        <Pop open={menu === "gear"} onClose={() => setMenu(null)}>
          <div style={{ padding: "4px 16px", fontWeight: 700 }}>Visual mode</div>
          {["light", "dark"].map((m) => <button key={m} style={ITEM} onClick={() => { onMode(m); setMenu(null); }}>{mode === m ? "✓ " : "  "}{m === "light" ? "Light" : "Dark"}</button>)}
          <div style={{ padding: "8px 16px 4px", fontWeight: 700 }}>Density</div>
          {["comfortable", "compact"].map((d) => <button key={d} style={ITEM} onClick={() => { onDensity(d); setMenu(null); }}>{density === d ? "✓ " : "  "}{d === "comfortable" ? "Comfortable" : "Compact"}</button>)}
        </Pop>
      </div>
      <span style={SEP} />
      <div style={{ position: "relative" }}>
        <button style={{ ...ICONBTN, gap: 6, fontSize: 13 }} aria-label="Region" onClick={() => toggle("region")}>{regionLabel} <Icon name="caret-down-filled" variant="inverted" size="small" /></button>
        <Pop open={menu === "region"} onClose={() => setMenu(null)} style={{ width: 300 }}>
          {regions.map(([id, label]) => (
            <button key={id} style={{ ...ITEM, display: "flex", justifyContent: "space-between", fontWeight: id === region ? 700 : 400 }} onClick={() => { onRegion(id); setMenu(null); }}>
              <span>{label}</span><span style={{ color: "#b6bec9" }}>{id}</span>
            </button>
          ))}
        </Pop>
      </div>
      <div style={{ position: "relative" }}>
        <button style={{ ...ICONBTN, gap: 6, fontSize: 13 }} aria-label="Account" onClick={() => toggle("acct")}>Vyomi (local) <Icon name="caret-down-filled" variant="inverted" size="small" /></button>
        <Pop open={menu === "acct"} onClose={() => setMenu(null)}>
          <div style={{ padding: "4px 16px 8px", color: "#b6bec9", fontSize: 12 }}>Account ID 123456789012 (simulated)</div>
          <a style={ITEM} href={classicHref("")}>Classic Vyomi console</a>
        </Pop>
      </div>
    </div>
  );
}
