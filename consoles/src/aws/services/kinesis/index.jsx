import Landing from "./Landing.jsx";
import Streams from "./Streams.jsx";
import CreateStream from "./CreateStream.jsx";
import StreamDetail from "./StreamDetail.jsx";

export default {
  nav: [
    { type: "link", text: "Data streams", href: "#/kinesis/streams" },
  ],
  routes: [
    { pattern: "/kinesis", component: Landing, crumbs: () => [{ text: "Amazon Kinesis", href: "#/kinesis" }] },
    { pattern: "/kinesis/home", component: Landing, crumbs: () => [{ text: "Amazon Kinesis", href: "#/kinesis/home" }] },
    { pattern: "/kinesis/streams", component: Streams, crumbs: () => [{ text: "Kinesis", href: "#/kinesis" }, { text: "Data streams", href: "#/kinesis/streams" }] },
    { pattern: "/kinesis/streams/create", component: CreateStream, crumbs: () => [{ text: "Kinesis", href: "#/kinesis" }, { text: "Data streams", href: "#/kinesis/streams" }, { text: "Create data stream", href: "#/kinesis/streams/create" }] },
    { pattern: "/kinesis/streams/:name", component: StreamDetail, crumbs: (p) => [{ text: "Kinesis", href: "#/kinesis" }, { text: "Data streams", href: "#/kinesis/streams" }, { text: p.name, href: `#/kinesis/streams/${p.name}` }] },
  ],
};
