/* Shared bits for the Load Balancing pages (LoadBalancers.jsx / TargetGroups.jsx): both
 * manage tags on ELBv2 resources (load balancers, target groups, listeners, rules) through
 * the same AddTags/RemoveTags/DescribeTags verbs. */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Table from "@cloudscape-design/components/table";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { TAG_I18N } from "./InstanceDetail.jsx";
import * as api from "./api.js";

export const opt = (v, label) => ({ value: v, label: label || v });
export const ALB_PROTOCOLS = ["HTTP", "HTTPS"];
export const NLB_PROTOCOLS = ["TCP", "TLS", "UDP", "TCP_UDP"];

// ELBv2's DescribeLoadBalancers/DescribeTargetGroups don't return tags — a separate
// DescribeTags call does, so this tab fetches (and re-fetches) its own tag set.
export function ElbTagsTab({ arn }) {
  const notify = useNotify();
  const [open, setOpen] = useState(false);
  const t = useAsync(() => api.describeElbTags(arn), [arn]);
  const rows = Object.entries(t.data || {}).map(([k, v]) => ({ key: k, value: v, existing: true }));
  const [edited, setEdited] = useState(rows);
  const save = async () => {
    const kept = edited.filter((x) => !x.markedForRemoval && x.key);
    const removed = edited.filter((x) => x.markedForRemoval && x.existing).map((x) => x.key);
    if (kept.length) await api.addElbTags([arn], Object.fromEntries(kept.map((x) => [x.key, x.value || ""])));
    if (removed.length) await api.removeElbTags([arn], removed);
    notify.success("Tags updated.");
    setOpen(false);
    t.reload();
  };
  return (
    <>
      <Table variant="container" items={rows} loading={t.loading}
        header={<Header variant="h2" counter={`(${rows.length})`} actions={<Button onClick={() => { setEdited(rows); setOpen(true); }}>Manage tags</Button>}>Tags</Header>}
        columnDefinitions={[{ id: "k", header: "Key", cell: (r) => r.key }, { id: "v", header: "Value", cell: (r) => r.value || "-" }]}
        empty={<Box textAlign="center" color="inherit">No tags</Box>} />
      <Modal visible={open} onDismiss={() => setOpen(false)} header="Manage tags" size="large"
        footer={<Box float="right"><Button variant="primary" onClick={save}>Save</Button></Box>}>
        <TagEditor tags={edited} onChange={({ detail }) => setEdited(detail.tags)} i18nStrings={TAG_I18N} />
      </Modal>
    </>
  );
}
