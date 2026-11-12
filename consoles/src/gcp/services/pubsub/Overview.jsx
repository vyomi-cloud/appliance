/* Overview — resource counts over the real topics/subscriptions/snapshots/schemas lists
 * (no dedicated native "overview" call; the console derives this the same way). */
import { Button, Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

function Stat({ label, value, href }) {
  return (
    <Section>
      <Stack spacing={0.5} alignItems="flex-start">
        <Typography variant="body2" color="text.secondary">{label}</Typography>
        <Typography variant="h2" component="div">{value ?? "—"}</Typography>
        <Button size="small" href={href} sx={{ ml: -1 }}>View</Button>
      </Stack>
    </Section>
  );
}

export default function Overview() {
  const topics = useAsync(() => api.listTopics(), []);
  const subs = useAsync(() => api.listSubscriptions(), []);
  const snaps = useAsync(() => api.listSnapshots(), []);
  const schemas = useAsync(() => api.listSchemas(), []);

  return (
    <>
      <PageHeader title="Overview" />
      <Stack useFlexGap direction="row" spacing={2} sx={{ flexWrap: "wrap" }}>
        <Stat label="Topics" value={topics.data?.length} href="#/pubsub/topics" />
        <Stat label="Subscriptions" value={subs.data?.length} href="#/pubsub/subscriptions" />
        <Stat label="Snapshots" value={snaps.data?.length} href="#/pubsub/snapshots" />
        <Stat label="Schemas" value={schemas.data?.length} href="#/pubsub/schemas" />
      </Stack>
    </>
  );
}
