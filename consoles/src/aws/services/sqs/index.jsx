import Landing from "./Landing.jsx";
import Queues from "./Queues.jsx";
import CreateQueue from "./CreateQueue.jsx";
import QueueDetail from "./QueueDetail.jsx";
import SendReceiveMessages from "./SendReceiveMessages.jsx";
import PurgeQueuePage from "./PurgeQueuePage.jsx";
import DeleteQueuePage from "./DeleteQueuePage.jsx";

export default {
  nav: [
    { type: "link", text: "Queues", href: "#/sqs/queues" },
  ],
  routes: [
    { pattern: "/sqs", component: Landing, crumbs: () => [{ text: "Amazon SQS", href: "#/sqs" }] },
    { pattern: "/sqs/home", component: Landing, crumbs: () => [{ text: "Amazon SQS", href: "#/sqs/home" }] },
    { pattern: "/sqs/queues", component: Queues, crumbs: () => [{ text: "Amazon SQS", href: "#/sqs" }, { text: "Queues", href: "#/sqs/queues" }] },
    { pattern: "/sqs/create-queue", component: CreateQueue, crumbs: () => [{ text: "Amazon SQS", href: "#/sqs" }, { text: "Queues", href: "#/sqs/queues" }, { text: "Create queue", href: "#/sqs/create-queue" }] },
    { pattern: "/sqs/queues/:name", component: QueueDetail, crumbs: (p) => [{ text: "Amazon SQS", href: "#/sqs" }, { text: "Queues", href: "#/sqs/queues" }, { text: p.name, href: `#/sqs/queues/${p.name}` }] },
    { pattern: "/sqs/queues/:name/edit", component: CreateQueue, crumbs: (p) => [{ text: "Amazon SQS", href: "#/sqs" }, { text: "Queues", href: "#/sqs/queues" }, { text: p.name, href: `#/sqs/queues/${p.name}` }, { text: "Edit", href: `#/sqs/queues/${p.name}/edit` }] },
    { pattern: "/sqs/queues/:name/send-receive", component: SendReceiveMessages, crumbs: (p) => [{ text: "Amazon SQS", href: "#/sqs" }, { text: "Queues", href: "#/sqs/queues" }, { text: p.name, href: `#/sqs/queues/${p.name}` }, { text: "Send and receive messages", href: `#/sqs/queues/${p.name}/send-receive` }] },
    { pattern: "/sqs/queues/:name/purge", component: PurgeQueuePage, crumbs: (p) => [{ text: "Amazon SQS", href: "#/sqs" }, { text: "Queues", href: "#/sqs/queues" }, { text: p.name, href: `#/sqs/queues/${p.name}` }, { text: "Purge queue", href: `#/sqs/queues/${p.name}/purge` }] },
    { pattern: "/sqs/queues/:name/delete", component: DeleteQueuePage, crumbs: (p) => [{ text: "Amazon SQS", href: "#/sqs" }, { text: "Queues", href: "#/sqs/queues" }, { text: p.name, href: `#/sqs/queues/${p.name}` }, { text: "Delete queue", href: `#/sqs/queues/${p.name}/delete` }] },
  ],
};
