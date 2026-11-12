import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

function ReplayModal({ archive, onDismiss, onDone }) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const r = await api.startReplay({
        ReplayName: `replay-${Date.now().toString(36)}`,
        EventSourceArn: archive.ArchiveArn || archive.arn,
        Destination: { Arn: archive.EventSourceArn },
      });
      notify.success(`Replay delivered ${r.State === "COMPLETED" ? "its archived events" : "started"} to ${archive.EventSourceArn.split("/").pop()}.`);
      onDone(); onDismiss();
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible onDismiss={onDismiss} header={<SpaceBetween direction="horizontal" size="xs" alignItems="center"><span>{`Replay ${archive.ArchiveName}`}</span><CapabilityBadge id="eventbridge.replay" /></SpaceBetween>}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={go}>Start replay</Button></SpaceBetween></Box>}>
      Replays every archived event matching this archive's pattern back to its source event bus's rules, in order.
    </Modal>
  );
}

export function ArchivesTable({ eventBusArn, resourceName = "Archives", variant = "container", createHref }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [replaying, setReplaying] = useState(null);
  const { data = [], loading, error, reload } = useAsync(() => api.listArchives(eventBusArn), [eventBusArn]);

  const del = async () => {
    try { await api.deleteArchive(sel[0].ArchiveName); notify.success(`Deleted archive ${sel[0].ArchiveName}.`); setSel([]); reload(); }
    catch (e) { notify.error(e); }
  };

  return (
    <>
      <ResourceTable
        variant={variant}
        resourceName={resourceName}
        description={<CapabilityBadge id="eventbridge.archives" />}
        items={data}
        loading={loading}
        error={error}
        onRefresh={reload}
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        trackBy="ArchiveName"
        filterPlaceholder="Find archives"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (a) => a.ArchiveName },
          { id: "status", header: "Status", cell: (a) => a.State },
          { id: "source", header: "Source", cell: (a) => a.EventSourceArn },
          { id: "created", header: "Created on", cell: (a) => fmtDate(a.CreationTime) },
          { id: "size", header: "Size in bytes", cell: (a) => a.SizeBytes ?? 0 },
          { id: "retention", header: "Retention days", cell: (a) => a.RetentionDays || "Indefinite" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} href={sel.length === 1 ? href("eventbridge", "archives", sel[0].ArchiveName, "edit") : undefined} onFollow={follow}>Edit</Button>
            <Button disabled={sel.length !== 1} onClick={del}>Delete</Button>
            <Button disabled={sel.length !== 1} onClick={() => setReplaying(sel[0])}>Replay</Button>
            {createHref && <Button variant="primary" href={createHref} onFollow={follow}>Create archive</Button>}
          </SpaceBetween>
        }
        empty={{ title: "No archives", subtitle: "No archives to display.", action: createHref && <Button href={createHref} onFollow={follow}>Create archive</Button> }}
      />
      {replaying && <ReplayModal archive={replaying} onDismiss={() => setReplaying(null)} onDone={reload} />}
    </>
  );
}

export default function Archives() {
  const { data: bus } = useAsync(() => api.describeEventBus("default"));
  return <ArchivesTable eventBusArn={bus?.Arn} resourceName="Archives" variant="full-page" createHref={href("eventbridge", "create-archive")} />;
}
