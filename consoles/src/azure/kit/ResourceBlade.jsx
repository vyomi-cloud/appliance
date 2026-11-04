/* A resource blade: title row (glyph, name, resource type, close) and the left resource menu
 * (searchable, with collapsible groups) beside the selected panel. Menu items are hash links,
 * so every panel is deep-linkable. */
import { useState } from "react";
import { Button, SearchBox } from "@fluentui/react-components";
import { ChevronDown16Regular, ChevronRight16Regular, Dismiss24Regular } from "@fluentui/react-icons";
import { Glyph } from "./common.jsx";

export function TitleRow({ title, subtitle, glyph, closeHref, actions }) {
  return (
    <div className="vy-title-row">
      {glyph}
      <div>
        <h1>{title}</h1>
        {subtitle && <div className="vy-subtitle">{subtitle}</div>}
      </div>
      {actions}
      {closeHref && <Button className="vy-close" appearance="subtle" icon={<Dismiss24Regular />} aria-label="Close" as="a" href={closeHref} />}
    </div>
  );
}

/** menu: [{id, label} | {group, items: [{id, label}]}] */
export default function ResourceBlade({ title, subtitle, glyph, closeHref, menu, active, hrefFor, children }) {
  const [q, setQ] = useState("");
  const [closed, setClosed] = useState({});
  const f = q.trim().toLowerCase();
  const hit = (it) => !f || it.label.toLowerCase().includes(f);
  const link = (it) => (
    <a key={it.id} href={hrefFor(it.id)} className={active === it.id ? "active" : undefined} aria-current={active === it.id ? "page" : undefined}>{it.label}</a>
  );
  return (
    <>
      <TitleRow title={title} subtitle={subtitle} glyph={glyph || <Glyph text={title.slice(0, 2).toUpperCase()} />} closeHref={closeHref} />
      <div className="vy-blade">
        <nav className="vy-rmenu" aria-label="Resource menu">
          <div className="vy-rmenu-search"><SearchBox size="small" placeholder="Search" value={q} onChange={(_, d) => setQ(d.value)} aria-label="Search resource menu" /></div>
          {menu.map((m) => {
            if (!m.group) return hit(m) ? link(m) : null;
            const items = m.items.filter(hit);
            if (!items.length) return null;
            const open = f || !closed[m.group];
            return (
              <div key={m.group}>
                <button className="vy-group" aria-expanded={!!open} onClick={() => setClosed((c) => ({ ...c, [m.group]: !c[m.group] }))}>
                  {open ? <ChevronDown16Regular /> : <ChevronRight16Regular />}{m.group}
                </button>
                {open && <div className="vy-sub">{items.map(link)}</div>}
              </div>
            );
          })}
        </nav>
        <div className="vy-bcontent">{children}</div>
      </div>
    </>
  );
}
