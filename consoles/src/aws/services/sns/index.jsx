import Landing from "./Landing.jsx";
import Dashboard from "./Dashboard.jsx";
import Topics from "./Topics.jsx";
import CreateTopic from "./CreateTopic.jsx";
import TopicDetail from "./TopicDetail.jsx";
import PublishMessage from "./PublishMessage.jsx";
import Subscriptions from "./Subscriptions.jsx";
import CreateSubscription from "./CreateSubscription.jsx";
import SubscriptionDetail from "./SubscriptionDetail.jsx";
import PushNotifications from "./PushNotifications.jsx";
import TextMessagingSms from "./TextMessagingSms.jsx";

export default {
  nav: [
    { type: "link", text: "Dashboard", href: "#/sns/dashboard" },
    { type: "link", text: "Topics", href: "#/sns/topics" },
    { type: "link", text: "Subscriptions", href: "#/sns/subscriptions" },
    { type: "section", text: "Mobile", items: [
      { type: "link", text: "Push notifications", href: "#/sns/mobile/push-notifications" },
      { type: "link", text: "Text messaging (SMS)", href: "#/sns/mobile/text-messaging" },
    ] },
  ],
  routes: [
    { pattern: "/sns", component: Landing, crumbs: () => [{ text: "Amazon SNS", href: "#/sns" }] },
    { pattern: "/sns/dashboard", component: Dashboard, crumbs: () => [{ text: "Amazon SNS", href: "#/sns" }, { text: "Dashboard", href: "#/sns/dashboard" }] },
    { pattern: "/sns/topics", component: Topics, crumbs: () => [{ text: "Amazon SNS", href: "#/sns" }, { text: "Topics", href: "#/sns/topics" }] },
    { pattern: "/sns/create-topic", component: CreateTopic, crumbs: () => [{ text: "Amazon SNS", href: "#/sns" }, { text: "Topics", href: "#/sns/topics" }, { text: "Create topic", href: "#/sns/create-topic" }] },
    { pattern: "/sns/topics/:name", component: TopicDetail, crumbs: (p) => [{ text: "Amazon SNS", href: "#/sns" }, { text: "Topics", href: "#/sns/topics" }, { text: p.name, href: `#/sns/topics/${p.name}` }] },
    { pattern: "/sns/topics/:name/edit", component: CreateTopic, crumbs: (p) => [{ text: "Amazon SNS", href: "#/sns" }, { text: "Topics", href: "#/sns/topics" }, { text: p.name, href: `#/sns/topics/${p.name}` }, { text: "Edit", href: `#/sns/topics/${p.name}/edit` }] },
    { pattern: "/sns/topics/:name/publish", component: PublishMessage, crumbs: (p) => [{ text: "Amazon SNS", href: "#/sns" }, { text: "Topics", href: "#/sns/topics" }, { text: p.name, href: `#/sns/topics/${p.name}` }, { text: "Publish message", href: `#/sns/topics/${p.name}/publish` }] },
    { pattern: "/sns/subscriptions", component: Subscriptions, crumbs: () => [{ text: "Amazon SNS", href: "#/sns" }, { text: "Subscriptions", href: "#/sns/subscriptions" }] },
    { pattern: "/sns/create-subscription", component: CreateSubscription, crumbs: () => [{ text: "Amazon SNS", href: "#/sns" }, { text: "Subscriptions", href: "#/sns/subscriptions" }, { text: "Create subscription", href: "#/sns/create-subscription" }] },
    { pattern: "/sns/subscriptions/:id", component: SubscriptionDetail, crumbs: (p) => [{ text: "Amazon SNS", href: "#/sns" }, { text: "Subscriptions", href: "#/sns/subscriptions" }, { text: p.id, href: `#/sns/subscriptions/${p.id}` }] },
    { pattern: "/sns/mobile/push-notifications", component: PushNotifications, crumbs: () => [{ text: "Amazon SNS", href: "#/sns" }, { text: "Mobile: Push notifications", href: "#/sns/mobile/push-notifications" }] },
    { pattern: "/sns/mobile/text-messaging", component: TextMessagingSms, crumbs: () => [{ text: "Amazon SNS", href: "#/sns" }, { text: "Text messaging (SMS)", href: "#/sns/mobile/text-messaging" }] },
  ],
};
