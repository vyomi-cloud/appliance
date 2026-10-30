import DashboardIcon from "@mui/icons-material/esm/Dashboard.js";
import MessageIcon from "@mui/icons-material/esm/MessageOutlined.js";
import MoveToInboxIcon from "@mui/icons-material/esm/MoveToInbox.js";
import CameraAltIcon from "@mui/icons-material/esm/CameraAlt.js";
import SchemaIcon from "@mui/icons-material/esm/Schema.js";
import Overview from "./Overview.jsx";
import Topics from "./Topics.jsx";
import CreateTopic from "./CreateTopic.jsx";
import TopicDetail from "./TopicDetail.jsx";
import PublishMessage from "./PublishMessage.jsx";
import Subscriptions from "./Subscriptions.jsx";
import CreateSubscription from "./CreateSubscription.jsx";
import SubscriptionDetail from "./SubscriptionDetail.jsx";
import Snapshots from "./Snapshots.jsx";
import Schemas from "./Schemas.jsx";

export default {
  nav: [
    { text: "Overview", href: "#/pubsub", icon: DashboardIcon },
    { text: "Topics", href: "#/pubsub/topics", icon: MessageIcon, match: ["#/pubsub/topics/create"] },
    { text: "Subscriptions", href: "#/pubsub/subscriptions", icon: MoveToInboxIcon, match: ["#/pubsub/subscriptions/create"] },
    { text: "Snapshots", href: "#/pubsub/snapshots", icon: CameraAltIcon },
    { text: "Schemas", href: "#/pubsub/schemas", icon: SchemaIcon },
  ],
  routes: [
    { pattern: "/pubsub", component: Overview },
    { pattern: "/pubsub/topics", component: Topics },
    { pattern: "/pubsub/topics/create", component: CreateTopic },
    { pattern: "/pubsub/topics/:name", component: TopicDetail },
    { pattern: "/pubsub/topics/:name/publish", component: PublishMessage },
    { pattern: "/pubsub/subscriptions", component: Subscriptions },
    { pattern: "/pubsub/subscriptions/create", component: CreateSubscription },
    { pattern: "/pubsub/subscriptions/:name", component: SubscriptionDetail },
    { pattern: "/pubsub/snapshots", component: Snapshots },
    { pattern: "/pubsub/schemas", component: Schemas },
  ],
};
