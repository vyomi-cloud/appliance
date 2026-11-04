/* Event Grid hub: the "Event Grid" landing dashboard (nav groups → Create/View). The sibling
 * resource-type pages (Namespaces, System topics, Domains, Partner events) have their own real
 * browse blade (SimpleList.jsx); Topics has its own (Topics.jsx). */
import { Link } from "@fluentui/react-components";
import { Glyph } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";

function Section({ title, children }) {
  return <section className="vy-section" style={{ marginBottom: 16 }}><h3>{title}</h3>{children}</section>;
}

function Tile({ label, createHref, viewHref }) {
  return (
    <div className="vy-form-row">
      <span className="vy-label">{label}</span>
      <span style={{ display: "flex", gap: 12 }}>
        {createHref && <Link href={createHref}>Create</Link>}
        {viewHref && <Link href={viewHref}>View</Link>}
      </span>
    </div>
  );
}

export function Overview() {
  return (
    <>
      <TitleRow title="Event Grid" glyph={<Glyph id="eventgrid" />} closeHref="#/" />
      <div className="vy-page">
        <Section title="MQTT broker">
          <Tile label="Namespaces" createHref="#/eventgrid/namespaces" viewHref="#/eventgrid/namespaces" />
        </Section>
        <Section title="Azure service events">
          <Tile label="System topics" createHref="#/eventgrid/systemtopics" viewHref="#/eventgrid/systemtopics" />
        </Section>
        <Section title="Custom events">
          <Tile label="Namespaces" createHref="#/eventgrid/namespaces" viewHref="#/eventgrid/namespaces" />
          <Tile label="Topics" createHref="#/eventgrid/topics/create" viewHref="#/eventgrid/topics" />
          <Tile label="Domains" createHref="#/eventgrid/domains" viewHref="#/eventgrid/domains" />
          <Tile label="Topics in Kubernetes" createHref="#/eventgrid/domains" viewHref="#/eventgrid/domains" />
        </Section>
        <Section title="Partner events">
          <Tile label="Available partners" viewHref="#/eventgrid/partnertopics" />
          <Tile label="Partner topics" createHref="#/eventgrid/partnertopics" viewHref="#/eventgrid/partnertopics" />
        </Section>
      </div>
    </>
  );
}
