/* Queue resource blade: Overview (Essentials + message counts) and the Service Bus
 * Explorer (send / peek / receive / complete / defer / move to dead letter), both backed
 * by the native Service Bus data plane (core/azure_servicebus_core.py). */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Input, Link, Radio, RadioGroup, Select, Table, TableBody, TableCell,
  TableHeader, TableHeaderCell, TableRow, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { ArrowClockwise20Regular, Delete20Regular, Mail20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { Essentials, ErrorBar, Glyph, Loading, fmtDate } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import * as api from "./api.js";

const MENU = [{ id: "overview", label: "Overview" }, { id: "explorer", label: "Service Bus Explorer" }];
const fmtSize = (mb) => (mb >= 1024 && mb % 1024 === 0 ? `${mb / 1024} GB` : `${mb || 0} MB`);

export default function QueueBlade({ params }) {
  const { rg, name, queue } = params;
  const panel = params.panel || "overview";
  const q = useAsync(() => api.getQueueArm(rg, name, queue), [rg, name, queue]);
  const self = `#/servicebus/${encodeURIComponent(rg)}/${encodeURIComponent(name)}/queues/${encodeURIComponent(queue)}`;
  const nsHref = `#/servicebus/${encodeURIComponent(rg)}/${encodeURIComponent(name)}/queues`;
  useEffect(() => { if (q.data) remember({ name: queue, type: "Service Bus queue", href: self }); }, [!!q.data, self]);

  let body;
  if (q.loading && !q.data) body = <Loading />;
  else if (q.error) body = <><ErrorBar error={q.error} title="Failed to load the queue" /><Link href={nsHref}>Back to Queues</Link></>;
  else {
    const a = q.data, reload = q.reload;
    body = panel === "explorer" ? <Explorer queue={queue} /> : <Overview a={a} reload={reload} rg={rg} ns={name} nsHref={nsHref} />;
  }

  return (
    <ResourceBlade title={panel === "overview" ? queue : `${queue} | Service Bus Explorer`} subtitle="Queue" glyph={<Glyph id="servicebus" />} closeHref={nsHref}
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}>
      {body}
    </ResourceBlade>
  );
}

function Overview({ a, reload, rg, ns, nsHref }) {
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const counts = useAsync(async () => ({
    active: (await api.peekMessages(a.name).catch(() => [])).length,
    dead: (await api.peekDeadLetter(a.name).catch(() => [])).length,
  }), [a.name]);
  const p = a.properties || {};
  const c = counts.data || { active: 0, dead: 0 };
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Queue commands">
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { reload(); counts.reload(); }}>Refresh</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Queue URL", `${api.namespaceEndpoint(ns)}${a.name}`],
          ["Max delivery count", p.maxDeliveryCount],
          ["Current size", fmtSize(0)],
          ["Max size", fmtSize(p.maxSizeInMegabytes)],
          ["Message time to live", api.fmtDuration(p.defaultMessageTimeToLive)],
        ]}
        right={[
          ["Lock duration", api.fmtDuration(p.lockDuration)],
          ["Auto-delete", p.autoDeleteOnIdleEnabled ? "Enabled" : "Disabled"],
          ["Duplicate detection", p.requiresDuplicateDetection ? "Enabled" : "Disabled"],
          ["Free space", fmtSize(Math.max(0, (p.maxSizeInMegabytes || 1024)))],
          ["Message counts", `${c.active} active, ${c.dead} dead-letter`],
        ]}
      />
      <section className="vy-section" style={{ marginTop: 12 }}><h3>Message counts</h3>
        <div className="vy-props">
          <div className="vy-kv"><span>Active</span><span>{c.active}</span></div>
          <div className="vy-kv"><span>Scheduled</span><span>0</span></div>
          <div className="vy-kv"><span>Dead-letter</span><span>{c.dead}</span></div>
          <div className="vy-kv"><span>Transfer</span><span>0</span></div>
          <div className="vy-kv"><span>Transfer dead-letter</span><span>0</span></div>
        </div>
      </section>
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="queue" names={[a.name]}
        onConfirm={async () => {
          await api.deleteQueueArm(rg, ns, a.name);
          await api.deleteQueueEntity(a.name);
          forget(`#/servicebus/${rg}/${ns}/queues/${a.name}`);
          notify.success(`Queue '${a.name}' was deleted.`, "Delete succeeded");
          navigate("servicebus", rg, ns, "queues");
        }} />
    </>
  );
}

// ── Service Bus Explorer (data plane: send / peek / receive / complete / defer / dead-letter) ──
function Explorer({ queue }) {
  const notify = useNotify();
  const [tab, setTab] = useState("queue");
  const [mode, setMode] = useState("peek");
  const [rows, setRows] = useState([]);
  const [sel, setSel] = useState(null);
  const [loading, setLoading] = useState(false);
  const [contentType, setContentType] = useState("Text/Plain");
  const [messageBody, setMessageBody] = useState("");
  const [sendMultiple, setSendMultiple] = useState(false);
  const [label, setLabel] = useState("");
  const [props, setProps] = useState([{ key: "", value: "" }]);

  const load = async (receive = false) => {
    setLoading(true); setSel(null);
    try {
      const xs = tab === "deadletter" ? await api.peekDeadLetter(queue)
        : receive ? await api.receiveMessages(queue) : await api.peekMessages(queue);
      setRows(xs);
    } catch (e) { notify.error(e, "Failed to load messages"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(false); }, [tab]);

  const send = async () => {
    try {
      const count = sendMultiple ? 3 : 1;
      const customProperties = Object.fromEntries(props.filter((p) => p.key).map((p) => [p.key, p.value]));
      for (let i = 0; i < count; i++) {
        await api.sendMessage(queue, sendMultiple ? `${messageBody} (${i + 1})` : messageBody, { label, contentType, customProperties });
      }
      notify.success(`Sent ${count} message${count > 1 ? "s" : ""} to '${queue}'.`, "Send succeeded");
      setMessageBody("");
      if (tab === "queue" && mode === "peek") load(false);
    } catch (e) { notify.error(e, "Failed to send message"); }
  };

  const act = async (action) => {
    if (!sel) return;
    try {
      if (action === "complete") await (tab === "deadletter" ? api.completeDeadLetterMessage(queue, sel.SequenceNumber) : api.completeMessage(queue, sel.SequenceNumber));
      else if (action === "defer") await api.deferMessage(queue, sel.SequenceNumber);
      else if (action === "deadletter") await api.deadLetterMessage(queue, sel.SequenceNumber, "Moved from Service Bus Explorer");
      else if (action === "resend") { await api.sendMessage(queue, sel.Body, { label: sel.Label, contentType: sel.ContentType }); if (tab === "deadletter") await api.completeDeadLetterMessage(queue, sel.SequenceNumber); }
      notify.success(`${{ complete: "Completed", defer: "Deferred", deadletter: "Moved to dead letter", resend: "Re-sent" }[action]} message ${sel.SequenceNumber}.`, "Message updated");
      load(false);
    } catch (e) { notify.error(e, "Message action failed"); }
  };

  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Service Bus Explorer commands">
        <ToolbarButton icon={<Mail20Regular />} disabled={!messageBody} onClick={send}>Send messages</ToolbarButton>
        <ToolbarButton disabled={!sel || tab !== "deadletter"} onClick={() => act("resend")}>Re-send messages</ToolbarButton>
        <ToolbarButton disabled={!sel} onClick={() => act("complete")}>Complete</ToolbarButton>
        <ToolbarButton disabled={!sel || tab === "deadletter"} onClick={() => act("defer")}>Defer</ToolbarButton>
        <ToolbarButton disabled={!sel || tab === "deadletter"} onClick={() => act("deadletter")}>Move to dead letter</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => load(false)}>Refresh</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Service Bus Explorer tabs">
        <Tab value="queue">Queue</Tab>
        <Tab value="deadletter">Dead-letter</Tab>
      </TabList>

      <section className="vy-section" style={{ marginTop: 12 }}><h3>Messages</h3>
        {tab === "queue" && (
          <RadioGroup layout="horizontal" value={mode} onChange={(_, d) => setMode(d.value)} aria-label="Mode">
            <Radio value="peek" label="Peek Mode" />
            <Radio value="receive" label="Receive Mode" />
          </RadioGroup>
        )}
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Button onClick={() => load(false)}>Peek from start</Button>
          <Button onClick={() => load(false)}>Peek next messages</Button>
          <Button disabled={tab !== "queue" || mode !== "receive"} onClick={() => load(true)}>Receive messages</Button>
        </div>
        {loading ? <Loading /> : (
          <Table size="small" aria-label="Messages" style={{ marginTop: 8 }}>
            <TableHeader><TableRow>
              <TableHeaderCell style={{ width: 32 }} />
              <TableHeaderCell>Sequence Number</TableHeaderCell><TableHeaderCell>Message ID</TableHeaderCell>
              <TableHeaderCell>Enqueued Time</TableHeaderCell><TableHeaderCell>Delivery Count</TableHeaderCell>
              <TableHeaderCell>State</TableHeaderCell><TableHeaderCell>Body Size</TableHeaderCell><TableHeaderCell>Label/Subject</TableHeaderCell>
            </TableRow></TableHeader>
            <TableBody>
              {rows.map((m) => (
                <TableRow key={m.SequenceNumber} aria-selected={sel?.SequenceNumber === m.SequenceNumber}>
                  <TableCell><Radio checked={sel?.SequenceNumber === m.SequenceNumber} onChange={() => setSel(m)} aria-label={`Select message ${m.SequenceNumber}`} /></TableCell>
                  <TableCell>{m.SequenceNumber}</TableCell>
                  <TableCell>{m.MessageId}</TableCell>
                  <TableCell>{fmtDate(m.EnqueuedTimeUtc)}</TableCell>
                  <TableCell>{m.DeliveryCount}</TableCell>
                  <TableCell>{m.State}</TableCell>
                  <TableCell>{m.BodySize}</TableCell>
                  <TableCell>{m.Label || "--"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {!loading && !rows.length && <p className="vy-muted" style={{ fontSize: 13 }}>No messages.</p>}
      </section>

      <section className="vy-section"><h3>Send messages</h3>
        <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 520 }}>
          <label>Content Type
            <Select value={contentType} onChange={(_, d) => setContentType(d.value)} aria-label="Content Type">
              <option>Text/Plain</option><option>Application/Json</option><option>Application/Xml</option>
            </Select>
          </label>
          <label>Message body
            <Textarea value={messageBody} onChange={(_, d) => setMessageBody(d.value)} aria-label="Message body" />
          </label>
          <Checkbox label="Send multiple messages" checked={sendMultiple} onChange={(_, d) => setSendMultiple(!!d.checked)} />
          <label>Broker properties (Label/Subject)
            <Input value={label} onChange={(_, d) => setLabel(d.value)} aria-label="Broker properties" placeholder="Label / subject" />
          </label>
          <Table size="small" aria-label="Custom properties">
            <TableHeader><TableRow><TableHeaderCell>Key</TableHeaderCell><TableHeaderCell>Value</TableHeaderCell></TableRow></TableHeader>
            <TableBody>
              {props.map((p, i) => (
                <TableRow key={i}>
                  <TableCell><Input size="small" value={p.key} onChange={(_, d) => setProps((xs) => { const n = [...xs]; n[i] = { ...n[i], key: d.value }; if (i === n.length - 1 && d.value) n.push({ key: "", value: "" }); return n; })} aria-label={`Custom property key ${i + 1}`} /></TableCell>
                  <TableCell><Input size="small" value={p.value} onChange={(_, d) => setProps((xs) => { const n = [...xs]; n[i] = { ...n[i], value: d.value }; return n; })} aria-label={`Custom property value ${i + 1}`} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Button appearance="primary" disabled={!messageBody} onClick={send}>Send</Button>
        </div>
      </section>
    </>
  );
}
