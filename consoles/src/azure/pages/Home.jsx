/* Portal Home: "Azure services" tile strip and the "Resources" list (Recent / Favorite). */
import { useState } from "react";
import { Button, Tab, TabList, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Link } from "@fluentui/react-components";
import { Add24Regular, ArrowRight24Regular } from "@fluentui/react-icons";
import { Glyph, NotSimulated } from "../kit/common.jsx";
import { recent } from "../kit/recent.js";
import { HOME_TILES, byId } from "../services/registry.js";

const ago = (t) => {
  const s = Math.max(1, Math.round((Date.now() - t) / 1000));
  if (s < 60) return "a few seconds ago";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} minute${m === 1 ? "" : "s"} ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.round(h / 24);
  return `${d} day${d === 1 ? "" : "s"} ago`;
};

export default function Home() {
  const [tab, setTab] = useState("recent");
  const rows = recent();
  return (
    <div className="vy-home">
      <h1 style={{ fontSize: 24, fontWeight: 600, margin: "4px 0 6px" }}>Welcome to Vyomi · Azure</h1>
      <div className="vy-muted" style={{ fontSize: 13 }}>A local simulation of the Azure portal. Everything here is backed by Vyomi and visible to your azure-* SDKs and the az CLI.</div>

      <h2>Azure services</h2>
      <div className="vy-tiles">
        <a className="vy-tile vy-link" href="#/allservices"><Add24Regular style={{ width: 32, height: 32 }} />Create a resource</a>
        {HOME_TILES.map((id) => byId[id]).map((s) => (
          <a key={s.id} className="vy-tile" href={`#/${s.id}`}><Glyph text={s.glyph[0]} color={s.glyph[1]} />{s.title}</a>
        ))}
        <a className="vy-tile vy-link" href="#/allservices"><ArrowRight24Regular style={{ width: 32, height: 32 }} />More services</a>
      </div>

      <h2>Resources</h2>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Resources">
        <Tab value="recent">Recent</Tab>
        <Tab value="favorite">Favorite</Tab>
      </TabList>
      {tab === "recent" ? (
        <>
          <Table size="small" aria-label="Recent resources" style={{ marginTop: 8 }}>
            <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell><TableHeaderCell>Last Viewed</TableHeaderCell></TableRow></TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.href}>
                  <TableCell><Link href={r.href}>{r.name}</Link></TableCell>
                  <TableCell>{r.type}</TableCell>
                  <TableCell>{ago(r.viewed)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {!rows.length && (
            <div className="vy-empty">
              <h3>No resources have been viewed recently</h3>
              <Button as="a" href="#/allresources" appearance="primary" style={{ marginTop: 8 }}>View all resources</Button>
            </div>
          )}
        </>
      ) : (
        <div style={{ marginTop: 12 }}><NotSimulated feature="Favorite resources" /></div>
      )}

      <h2>Navigate</h2>
      <div className="vy-tiles" style={{ gap: 24 }}>
        <Link href="#/subscriptions">Subscriptions</Link>
        <Link href="#/resourcegroups">Resource groups</Link>
        <Link href="#/allresources">All resources</Link>
      </div>
    </div>
  );
}
