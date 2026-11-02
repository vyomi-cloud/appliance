/* Ancillary EventBridge surfaces this run doesn't back with a real backend (Pipes, the
 * Schema registry, Connections/API destinations, Global endpoints, Partner event sources,
 * the Learn/Sandbox/Quick starts developer pages). Each still gets a real v4 route whose
 * title and tabs are real navigation; GapPage (./common.jsx) discloses every column/
 * action/section/field the native page carries, by name, from the spec itself. */
import GapPage from "./common.jsx";

const PAGES = [
  { id: "partner-event-sources", path: "partner-event-sources", title: "Partner event sources" },
  { id: "schemas", path: "schemas", title: "Schemas" },
  { id: "learn", path: "learn", title: "Learn" },
  { id: "quick-starts", path: "quick-starts", title: "Quick starts" },
];

export default PAGES.map((p) => ({ ...p, component: () => <GapPage pageId={p.id} /> }));
