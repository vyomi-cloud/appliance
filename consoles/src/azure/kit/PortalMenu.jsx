/* The hamburger flyout: Create a resource, Home, Dashboard, All services, then the viewer's favorites
 * (the same list the All services blade stars — see portalFavorites.js). */
import { useEffect } from "react";
import { Add20Regular, DataBarVertical20Regular, Home20Filled, Navigation20Regular, TextBulletListLtr20Regular } from "@fluentui/react-icons";
import { Glyph } from "./common.jsx";
import { entry } from "./allServicesModel.js";
import { useFavorites } from "./portalFavorites.js";

export default function PortalMenu({ onClose }) {
  const favs = useFavorites();
  useEffect(() => {
    const on = (e) => { if (e.key === "Escape") onClose(); };
    addEventListener("keydown", on);
    return () => removeEventListener("keydown", on);
  }, []);
  return (
    <>
      <div className="vy-scrim" style={{ inset: 0 }} onClick={onClose} />
      <nav className="vy-pm" aria-label="Portal menu">
        <div className="vy-pm-top"><button type="button" aria-label="Hide portal menu" onClick={onClose}><Navigation20Regular /></button></div>
        <a className="vy-pm-item" href="#/allservices"><span className="vy-pm-ic" style={{ color: "#57a300" }}><Add20Regular /></span><span>Create a resource</span></a>
        <a className="vy-pm-item" href="#/"><span className="vy-pm-ic" style={{ color: "#0078d4" }}><Home20Filled /></span><span>Home</span></a>
        <a className="vy-pm-item" href="#/"><span className="vy-pm-ic" style={{ color: "#57a300" }}><DataBarVertical20Regular /></span><span>Dashboard</span></a>
        <a className="vy-pm-item" href="#/allservices"><span className="vy-pm-ic" style={{ color: "#57a300" }}><TextBulletListLtr20Regular /></span><span>All services</span></a>
        <div className="vy-pm-fav"><span style={{ color: "#0078d4", fontSize: 14, fontWeight: 400, textTransform: "none" }}>★</span><span>Favorites</span><i /></div>
        <div className="vy-pm-list">
          {favs.filter((n) => entry(n).simulated).map((n) => { const e = entry(n); return (
            <a key={n} className="vy-pm-item" href={e.href}><span className="vy-pm-ic"><Glyph id={e.icon} size={20} /></span><span>{n}</span></a>
          ); })}
        </div>
      </nav>
    </>
  );
}
