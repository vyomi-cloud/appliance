/* "All services": every service Vyomi simulates, grouped by category, filterable. */
import { useState } from "react";
import { Badge, SearchBox } from "@fluentui/react-components";
import { Glyph } from "../kit/common.jsx";
import { TitleRow } from "../kit/ResourceBlade.jsx";
import { CATEGORIES, SERVICES } from "../services/registry.js";

export default function AllServices() {
  const [q, setQ] = useState("");
  const f = q.trim().toLowerCase();
  const shown = SERVICES.filter((s) => !f || s.title.toLowerCase().includes(f) || s.category.toLowerCase().includes(f));
  return (
    <>
      <TitleRow title="All services" subtitle="Services simulated by Vyomi" closeHref="#/" />
      <div className="vy-page">
        <SearchBox placeholder="Search all services" value={q} onChange={(_, d) => setQ(d.value)} style={{ width: 320, marginBottom: 16 }} aria-label="Search all services" />
        {CATEGORIES.map((c) => {
          const xs = shown.filter((s) => s.category === c);
          if (!xs.length) return null;
          return (
            <section key={c} className="vy-section">
              <h3>{c}</h3>
              <div className="vy-tiles">
                {xs.map((s) => (
                  <a key={s.id} className="vy-tile" style={{ width: 132 }} href={`#/${s.id}`}>
                    <Glyph text={s.glyph[0]} color={s.glyph[1]} />{s.title}
                    {!s.load && <Badge size="small" appearance="tint" color="informative">classic console</Badge>}
                  </a>
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </>
  );
}
