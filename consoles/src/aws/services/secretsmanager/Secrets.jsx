/* Secrets list — the service's one native resource list. "Recommended actions" is a real
 * read of the loaded secrets (no rotation configured), not a canned disclaimer. */
import { useMemo, useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { href, follow, navigate } from "../../../common/router.js";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

function RecommendedActionsModal({ secrets, visible, onDismiss }) {
  const noRotation = secrets.filter((s) => !s.RotationEnabled);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Recommended actions"
      footer={<Box float="right"><Button variant="primary" onClick={onDismiss}>Close</Button></Box>}>
      <SpaceBetween size="m">
        {noRotation.length ? (
          <Box>
            <b>{noRotation.length} secret{noRotation.length === 1 ? "" : "s"} without rotation configured.</b>
            <ul>{noRotation.map((s) => <li key={s.ARN}>{s.Name}</li>)}</ul>
          </Box>
        ) : <Box>Every secret has rotation configured.</Box>}
      </SpaceBetween>
    </Modal>
  );
}

export default function Secrets() {
  const t = useAsync(() => api.listSecrets(), []);
  const [recommend, setRecommend] = useState(false);
  const secrets = useMemo(() => t.data || [], [t.data]);
  return (
    <>
      <ResourceTable
        resourceName="Secrets"
        items={secrets}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="ARN"
        filterPlaceholder="Filter secrets by name, description, tag key, tag value, owning service or primary Region"
        empty={{ title: "No secrets", subtitle: "You don't have any secrets.", action: <Button onClick={() => navigate("secretsmanager", "newsecret")}>Store a new secret</Button> }}
        columns={[
          { id: "name", header: "Secret name", isRowHeader: true, sortingField: "Name", cell: (s) => <Link href={href("secretsmanager", "secret", s.Name)} onFollow={follow}>{s.Name}</Link> },
          { id: "desc", header: "Description", cell: (s) => s.Description || "-" },
          { id: "retrieved", header: "Last retrieved (UTC)", cell: (s) => fmtDate(s.LastAccessedDate) },
          { id: "created", header: "Created on (UTC)", cell: (s) => fmtDate(s.CreatedDate) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => setRecommend(true)}>Recommended actions</Button>
            <Button variant="primary" onClick={() => navigate("secretsmanager", "newsecret")}>Store a new secret</Button>
          </SpaceBetween>
        }
      />
      <RecommendedActionsModal secrets={secrets} visible={recommend} onDismiss={() => setRecommend(false)} />
    </>
  );
}
