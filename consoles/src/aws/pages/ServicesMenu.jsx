/* The services drawer (top bar ▦), laid out like the native console: a dark panel from the
 * left — section list (Recently visited, Favorites, All services, categories A–Z) and the
 * services of the selected section (bold name, one-line description, favourite star). */
import { useEffect, useState } from "react";
import Icon from "@cloudscape-design/components/icon";
import { CATEGORIES, SERVICES, byId } from "../services/registry.js";
import ServiceIcon from "../../common/icons/ServiceIcon.jsx";

const read = (k, d) => { try { return JSON.parse(localStorage.getItem(`vyomi.v4.${k}`)) ?? d; } catch { return d; } };
const write = (k, v) => { try { localStorage.setItem(`vyomi.v4.${k}`, JSON.stringify(v)); } catch {} };

const PANEL = { position: "fixed", top: 40, left: 0, bottom: 32, zIndex: 1500, display: "flex", boxShadow: "4px 0 24px rgba(0,0,0,.4)",
  fontFamily: '"Open Sans","Helvetica Neue",Roboto,Arial,sans-serif', color: "#fff" };
const NAV = { width: 180, background: "#0f141a", padding: "12px 0", overflowY: "auto", borderRight: "1px solid #232f3e" };
const LIST = { width: 340, background: "#192534", overflowY: "auto" };
const navBtn = (active) => ({ display: "block", width: "100%", textAlign: "left", background: "none", border: 0, cursor: "pointer",
  padding: "5px 18px", fontSize: 13, fontWeight: active ? 700 : 400, color: active ? "#539fe5" : "#fff" });

export default function ServicesMenu({ onClose }) {
  const [section, setSection] = useState("recent");
  const [favs, setFavs] = useState(read("favorites", []));
  useEffect(() => {
    const esc = (e) => e.key === "Escape" && onClose();
    addEventListener("keydown", esc);
    return () => removeEventListener("keydown", esc);
  }, []);
  const toggleFav = (id) => { const f = favs.includes(id) ? favs.filter((x) => x !== id) : [...favs, id]; setFavs(f); write("favorites", f); };
  const recent = read("recent", []).map((id) => byId[id]).filter(Boolean);
  const cats = [...CATEGORIES].sort();
  const sections = { recent: ["Recently visited", recent], favorites: ["Favorites", favs.map((id) => byId[id]).filter(Boolean)], all: ["All services", [...SERVICES].sort((a, b) => a.title.localeCompare(b.title))] };
  for (const c of cats) sections[`cat:${c}`] = [c, SERVICES.filter((s) => s.category === c)];
  const [title, list] = sections[section];
  const go = (s) => { location.hash = `/${s.id}`; onClose(); };
  const empty = { recent: "Services you open appear here.", favorites: "Star a service to add it to your favorites." }[section];

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: "40px 0 32px 0", zIndex: 1499 }} aria-hidden />
      <div style={PANEL} role="dialog" aria-label="Services" className="vy-dark-chrome">
        <nav style={NAV} aria-label="Service categories">
          {["recent", "favorites", "all"].map((k) => <button key={k} style={navBtn(section === k)} onClick={() => setSection(k)}>{sections[k][0]}</button>)}
          <div style={{ height: 1, background: "#414d5c", margin: "12px 18px" }} />
          {cats.map((c) => <button key={c} style={navBtn(section === `cat:${c}`)} onClick={() => setSection(`cat:${c}`)}>{c}</button>)}
        </nav>
        <div style={LIST}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: "1px solid #414d5c" }}>
            <span style={{ fontWeight: 700, fontSize: 16 }}>{title}</span>
            <button onClick={onClose} aria-label="Close" style={{ background: "none", border: 0, cursor: "pointer", padding: 4 }}><Icon name="close" variant="inverted" /></button>
          </div>
          {list.length ? list.map((s) => (
            <div key={s.id} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "10px 20px" }}>
              <ServiceIcon cloud="aws" id={s.icon || s.id} category={s.category} size={32} style={{ marginTop: 1 }} />
              <button onClick={() => go(s)} style={{ flex: 1, textAlign: "left", background: "none", border: 0, cursor: "pointer", color: "#fff", padding: 0, marginLeft: 4 }}>
                <div style={{ fontWeight: 700, fontSize: 14 }}>{s.title}</div>
                <div style={{ fontSize: 12, color: "#b6bec9", marginTop: 3, lineHeight: 1.35 }}>{s.description}{!s.load ? " · classic console" : ""}</div>
              </button>
              <button onClick={() => toggleFav(s.id)} aria-label={favs.includes(s.id) ? `Remove ${s.title} from favorites` : `Add ${s.title} to favorites`}
                style={{ background: "none", border: 0, cursor: "pointer", padding: 2 }}>
                <Icon name={favs.includes(s.id) ? "star-filled" : "star"} variant="inverted" />
              </button>
            </div>
          )) : <div style={{ padding: "14px 20px", color: "#b6bec9", fontSize: 13 }}>{empty}</div>}
        </div>
      </div>
    </>
  );
}
