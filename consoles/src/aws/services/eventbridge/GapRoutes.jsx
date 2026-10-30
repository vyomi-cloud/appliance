/* Ancillary EventBridge surfaces this run doesn't back with a real backend (Pipes, the
 * Schema registry, Connections/API destinations, Global endpoints, Partner event sources,
 * the Learn/Sandbox/Quick starts developer pages). Each still gets a real v4 route whose
 * title and tabs are real navigation; GapPage (./common.jsx) discloses every column/
 * action/section/field the native page carries, by name, from the spec itself. */
import GapPage from "./common.jsx";

const PAGES = [
  { id: "pipes", path: "pipes", title: "Pipes" },
  { id: "create-pipe", path: "create-pipe", title: "Create pipe" },
  { id: "partner-event-sources", path: "partner-event-sources", title: "Partner event sources" },
  { id: "api-destinations", path: "api-destinations", title: "API destinations" },
  { id: "create-api-destination", path: "create-api-destination", title: "Create API destination" },
  { id: "connections", path: "connections", title: "Connections" },
  { id: "create-connection", path: "create-connection", title: "Create connection" },
  { id: "schemas", path: "schemas", title: "Schemas" },
  { id: "global-endpoints", path: "global-endpoints", title: "Global endpoints" },
  { id: "create-global-endpoint", path: "create-global-endpoint", title: "Create global endpoint" },
  { id: "learn", path: "learn", title: "Learn" },
  { id: "sandbox", path: "sandbox", title: "Sandbox" },
  { id: "quick-starts", path: "quick-starts", title: "Quick starts" },
];

export default PAGES.map((p) => ({ ...p, component: () => <GapPage pageId={p.id} /> }));
