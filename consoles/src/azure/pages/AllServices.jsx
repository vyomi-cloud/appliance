/* "All services" blade — mirrors the real portal's All services page: category list (All / Favorites /
 * Recents / Categories), "Filter services", Service providers + Release Status filters, Detail view toggle,
 * the featured row, per-category groups of service cards with a favorite star, Create and View.
 * Names, descriptions and ordering come from the captured real catalog (services/allServicesCatalog.js);
 * entries Vyomi does not simulate stay listed and open an honest "not simulated" page. */
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown16Regular, ChevronUp16Regular, Info16Regular, Star20Filled, Star20Regular } from "@fluentui/react-icons";
import { Menu, MenuItemRadio, MenuList, MenuPopover, MenuTrigger } from "@fluentui/react-components";
import { Glyph, NotSimulated } from "../kit/common.jsx";
import { useRoute } from "../../common/router.js";
import { recent } from "../kit/recent.js";
import { ALL_VIEW, CAT_LIST, ENTRIES, FEATURED, GROUPS } from "../services/allServicesCatalog.js";
import { TILE_ALIAS, allNames, entry, findBySlug } from "../kit/allServicesModel.js";
import { toggleFavorite, useFavorites } from "../kit/portalFavorites.js";
import { useK8sLock, LockBadge } from "../../common/k8sTier.jsx";

const PROVIDERS = ["All", "Microsoft", "Partner"];
const STATUSES = ["All", "Generally available", "Preview"];
const FEATURED_TILES = FEATURED.filter((n) => !["Resource groups", "SQL databases", "Virtual networks"].includes(n)).map((n) => ({ label: n === "Cost Management + Billing" ? "Cost Management" : n, name: TILE_ALIAS[n] || n }));
const catTitle = (id) => (CAT_LIST.find(([k]) => k === id) || [])[1] || id;

const nav = (cat) => { location.hash = cat && cat !== "All" ? `/allservices?cat=${encodeURIComponent(cat)}` : "/allservices"; };

function Star({ name, on }) {
  return (
    <button type="button" className="vy-as-star" aria-label={on ? "Remove service from favorites" : "Add service to favorites"} aria-pressed={on}
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleFavorite(name); }}>
      {on ? <Star20Filled /> : <Star20Regular />}
    </button>
  );
}

function Tag({ tag }) { return tag ? <span className={`vy-as-tag vy-as-tag-${tag.toLowerCase()}`}>{tag}</span> : null; }

function Card({ name, favs, k8s }) {
  const e = entry(name);
  return (
    <li className="vy-as-card" data-service={name}>
      <div className="vy-as-card-head">
        <Glyph id={e.icon} size={32} />
        <a className="vy-as-card-name" href={e.href} title={name}>{name}</a>
        <Star name={name} on={favs.includes(name)} />
      </div>
      <div className="vy-as-card-body" title={e.desc}>{e.desc}</div>
      <div className="vy-as-card-foot">
        {e.create && (e.createHref
          ? <a className="vy-as-create" href={e.createHref}>Create{e.dropdown && <ChevronDown16Regular />}</a>
          : <a className="vy-as-create" href={e.href}>Create{e.dropdown && <ChevronDown16Regular />}</a>)}
        <a className="vy-as-view" href={e.href}>View</a>
        {e.reg?.id === "aks" && k8s.ready && k8s.locked && <LockBadge />}
        {!e.simulated && <span className="vy-as-ns">Not simulated</span>}
        <Tag tag={e.tag} />
      </div>
    </li>
  );
}

function Row({ name, q, active, k8s }) {
  const e = entry(name);
  const i = q ? name.toLowerCase().indexOf(q) : -1;
  return (
    <li className={`vy-as-row${active ? " active" : ""}`} data-service={name}>
      <a href={e.href} title={name}>
        <Glyph id={e.icon} size={20} />
        <span className="vy-as-row-name">
          {i < 0 ? name : <>{name.slice(0, i)}<b>{name.slice(i, i + q.length)}</b>{name.slice(i + q.length)}</>}
        </span>
        {e.reg?.id === "aks" && k8s.ready && k8s.locked && <LockBadge />}
        {!e.simulated && <span className="vy-as-ns">Not simulated</span>}
        <Tag tag={e.tag} />
      </a>
    </li>
  );
}

function SectionHead({ title, count, open, onToggle, link, star, name, favs }) {
  return (
    <div className="vy-as-sec-head">
      {link && <Glyph id={entry(name || title).icon} size={24} />}
      {link ? <a className="vy-as-sec-title vy-as-sec-link" href={entry(name || title).href}>{title}</a> : <h3 className="vy-as-sec-title">{title}</h3>}
      {count != null && <span className="vy-as-sec-count">({count})</span>}
      {star && <Star name={name || title} on={favs.includes(name || title)} />}
      <span className="vy-as-sec-line" />
      {onToggle && <button type="button" className="vy-as-collapse" aria-label={open ? `Collapse ${title}` : `Expand ${title}`} aria-expanded={open} onClick={onToggle}>{open ? <ChevronUp16Regular /> : <ChevronDown16Regular />}</button>}
    </div>
  );
}

function NotSimulatedService({ name }) {
  const e = entry(name);
  return (
    <div className="vy-as vy-as-ns-page">
      <div className="vy-as-title"><h1>{name}</h1></div>
      <div className="vy-page">
        <NotSimulated feature={`The ${name} blade`} note={<>Vyomi does not simulate {name} yet. <a href="#/allservices">Back to All services</a>.</>} />
      </div>
    </div>
  );
}

export default function AllServices() {
  const route = useRoute();
  const k8s = useK8sLock("azure");
  const favs = useFavorites();
  const [q, setQ] = useState("");
  const [detail, setDetail] = useState(() => { try { return localStorage.getItem("vyomi.v4.azure.allservices.detail") !== "0"; } catch { return true; } });
  const [provider, setProvider] = useState("All");
  const [status, setStatus] = useState("All");
  const [closed, setClosed] = useState({});
  const [active, setActive] = useState(0);
  const cat = route.query.cat || "All";
  const f = q.trim().toLowerCase();
  const sub = route.parts[1];
  useEffect(() => { try { localStorage.setItem("vyomi.v4.azure.allservices.detail", detail ? "1" : "0"); } catch {} }, [detail]);
  useEffect(() => { setActive(0); }, [f, cat, provider, status]);

  const pass = (n) => {
    const t = entry(n).tag;
    if (provider === "Microsoft" && t === "PARTNER") return false;
    if (provider === "Partner" && t !== "PARTNER") return false;
    if (status === "Preview" && t !== "PREVIEW") return false;
    if (status === "Generally available" && t === "PREVIEW") return false;
    return true;
  };

  const flat = useMemo(() => {
    if (!f) return [];
    const seen = new Set(); const out = [];
    const pool = cat === "All" ? allNames() : (GROUPS[cat] || []).flatMap((g) => [g.k === "l" ? g.n : null, ...g.i]).filter(Boolean);
    for (const n of pool) if (!seen.has(n) && n.toLowerCase().includes(f) && pass(n)) { seen.add(n); out.push(n); }
    return out.sort((a, b) => (b.toLowerCase().startsWith(f) ? 1 : 0) - (a.toLowerCase().startsWith(f) ? 1 : 0));
  }, [f, cat, provider, status]);

  if (sub) { const n = findBySlug(sub); if (n) return <NotSimulatedService name={n} />; }

  const recents = recent();
  const sorted = (xs) => xs.slice().sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
  const onKey = (e) => {
    if (!f || !flat.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, flat.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    if (e.key === "Enter") location.hash = entry(flat[active]).href.slice(1);
  };

  const Cards = ({ names }) => <ul className="vy-as-cards">{names.map((n, i) => <Card key={n + i} name={n} favs={favs} k8s={k8s} />)}</ul>;
  const Rows = ({ names }) => <ul className="vy-as-rows">{names.map((n, i) => <Row key={n + i} name={n} q="" k8s={k8s} />)}</ul>;
  const List = ({ names }) => (detail ? <Cards names={names} /> : <Rows names={names} />);

  let body;
  if (f) {
    body = flat.length
      ? <ul className="vy-as-rows vy-as-results">{flat.map((n, i) => <Row key={n} name={n} q={f} active={i === active} k8s={k8s} />)}</ul>
      : <div className="vy-as-empty"><div className="vy-as-empty-art" aria-hidden><i /><i /><i /></div><div>There are no results matching your filter query</div></div>;
  } else if (cat === "Favorites") {
    const xs = sorted(favs.filter(pass));
    body = xs.length ? <List names={xs} /> : <div className="vy-as-empty"><div>No favorites yet. Select the star on a service to add it.</div></div>;
  } else if (cat === "Recents") {
    const xs = recents.slice(0, 20);
    body = xs.length
      ? <ul className="vy-as-rows">{xs.map((r) => <li key={r.href} className="vy-as-row"><a href={r.href}>{r.icon ? <Glyph id={r.icon} size={20} /> : null}<span className="vy-as-row-name">{r.name || r.title || r.href}</span></a></li>)}</ul>
      : <div className="vy-as-empty"><div>No recent services or resources in this session.</div></div>;
  } else if (cat === "All") {
    body = CAT_LIST.map(([id, title]) => {
      const names = (ALL_VIEW[id] || []).filter(pass);
      if (!names.length) return null;
      const open = !closed[id];
      return (
        <section key={id} className="vy-as-sec">
          <SectionHead title={title} count={names.length} open={open} onToggle={() => setClosed((c) => ({ ...c, [id]: open }))} />
          {open && <List names={names} />}
        </section>
      );
    });
  } else {
    body = (GROUPS[cat] || []).map((g, gi) => {
      const names = g.i.filter(pass);
      if (!names.length && g.k !== "l") return null;
      return (
        <section key={gi} className="vy-as-sec vy-as-grp">
          <SectionHead title={g.n} link={g.k === "l"} star={g.k === "l"} favs={favs} />
          {g.k === "l" && !names.length && g.d && <div className="vy-as-grp-desc">{g.d}</div>}
          {names.length > 0 && <List names={names} />}
        </section>
      );
    });
  }

  return (
    <div className="vy-as">
      <div className="vy-as-title">
        <h1>All services</h1>
        {cat !== "All" && <><span className="vy-as-bar" /><h2>{catTitle(cat)}</h2></>}
      </div>
      <div className="vy-as-layout">
        <nav className="vy-as-cats" aria-label="Service categories">
          {["All", "Favorites", "Recents"].map((c) => <button key={c} type="button" className={`vy-as-cat${cat === c ? " sel" : ""}`} aria-current={cat === c} onClick={() => nav(c)}>{c}</button>)}
          <div className="vy-as-cats-title">Categories</div>
          {CAT_LIST.map(([id, title]) => <button key={id} type="button" data-category={id} className={`vy-as-cat${cat === id ? " sel" : ""}`} aria-current={cat === id} onClick={() => nav(id)}>{title}</button>)}
        </nav>
        <main className="vy-as-main">
          <div className="vy-as-top">
            <div className="vy-as-filter">
              <input type="text" value={q} placeholder="Filter services" aria-label="Filter services" onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} />
              {q && <button type="button" className="vy-as-clear" aria-label="Clear filter" onClick={() => setQ("")}>×</button>}
            </div>
            <span className="vy-as-info" title="Filter services by name"><Info16Regular /></span>
            <Menu checkedValues={{ provider: [provider] }} onCheckedValueChange={(_, d) => setProvider(d.checkedItems[0])}>
              <MenuTrigger disableButtonEnhancement><button type="button" className="vy-as-pill">Service providers : <b>{provider}</b></button></MenuTrigger>
              <MenuPopover><MenuList>{PROVIDERS.map((p) => <MenuItemRadio key={p} name="provider" value={p}>{p}</MenuItemRadio>)}</MenuList></MenuPopover>
            </Menu>
            <Menu checkedValues={{ status: [status] }} onCheckedValueChange={(_, d) => setStatus(d.checkedItems[0])}>
              <MenuTrigger disableButtonEnhancement><button type="button" className="vy-as-pill">Release Status : <b>{status}</b></button></MenuTrigger>
              <MenuPopover><MenuList>{STATUSES.map((p) => <MenuItemRadio key={p} name="status" value={p}>{p}</MenuItemRadio>)}</MenuList></MenuPopover>
            </Menu>
            {!f && (
              <label className="vy-as-detail">
                <button type="button" role="switch" aria-checked={detail} aria-label="Detail view" className={`vy-as-switch${detail ? " on" : ""}`} onClick={() => setDetail((d) => !d)}><i /></button>
                <span>Detail view</span>
              </label>
            )}
          </div>
          {!f && cat === "All" && (
            <ul className="vy-as-featured">
              {FEATURED_TILES.map((t) => { const e = entry(t.name); return (
                <li key={t.name}><a href={e.href}><Glyph id={e.icon} size={32} /><span>{t.label}</span></a></li>
              ); })}
            </ul>
          )}
          {body}
        </main>
      </div>
    </div>
  );
}
