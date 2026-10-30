/* Object details: metadata from objects.get, download via ?alt=media, delete. */
import { useState } from "react";
import { Box, Breadcrumbs, Button, CircularProgress, IconButton, Stack, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import DownloadIcon from "@mui/icons-material/esm/Download.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue, NotSimulated, PageHeader, Section } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import * as api from "./api.js";

export default function ObjectDetail({ params, query }) {
  const notify = useNotify();
  const bucket = params.name;
  const name = query.name || "";
  const [del, setDel] = useState(false);
  const { data: o, loading, error } = useAsync(() => api.getObject(bucket, name), [bucket, name]);
  const parts = name.split("/");
  const parent = parts.slice(0, -1).join("/");
  const back = hashHref("storage", "browser", bucket) + (parent ? `?prefix=${encodeURIComponent(parent + "/")}` : "");
  return (
    <>
      <PageHeader title="Object details" back={<IconButton aria-label="Back" href={back}><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button startIcon={<DownloadIcon />} href={api.downloadUrl(bucket, name)} download={parts[parts.length - 1]} disabled={!o}>Download</Button>
          <Button startIcon={<DeleteIcon />} onClick={() => setDel(true)} disabled={!o}>Delete</Button>
        </>} />
      <Breadcrumbs sx={{ mb: 2 }} aria-label="Object path">
        <Link href="#/storage/browser">Buckets</Link>
        <Link href={hashHref("storage", "browser", bucket)}>{bucket}</Link>
        {parts.slice(0, -1).map((p, i) => <Link key={i} href={hashHref("storage", "browser", bucket) + `?prefix=${encodeURIComponent(parts.slice(0, i + 1).join("/") + "/")}`}>{p}</Link>)}
        <Typography variant="body2" sx={{ fontWeight: 500 }}>{parts[parts.length - 1]}</Typography>
      </Breadcrumbs>
      <ErrorAlert error={error} title="Failed to load object" />
      {loading && <CircularProgress size={24} />}
      {o && (
        <Stack spacing={2}>
          <Section title="Overview">
            <KeyValue items={[
              ["Type", o.contentType], ["Size", fmtBytes(o.size)], ["Created", fmtDate(o.timeCreated)], ["Last modified", fmtDate(o.updated)],
              ["Storage class", api.classLabel(o.storageClass)], ["gsutil URI", `gs://${bucket}/${o.name}`],
              ["Authenticated URL", <Link key="u" href={api.downloadUrl(bucket, o.name)} target="_blank" rel="noreferrer">Download link (Vyomi wire)</Link>],
              ["Generation", o.generation], ["Metageneration", o.metageneration],
              ["Hash (CRC32C)", o.crc32c], ["Hash (MD5)", o.md5Hash],
            ]} />
          </Section>
          <Section title="Custom metadata">
            {o.metadata && Object.keys(o.metadata).length
              ? <KeyValue items={Object.entries(o.metadata)} />
              : <Typography variant="body2" color="text.secondary">No custom metadata.</Typography>}
          </Section>
          <Box><NotSimulated compact feature="Editing object metadata, holds and object retention" /></Box>
        </Stack>
      )}
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete object?" confirmText="DELETE"
        onConfirm={async () => { await api.deleteObject(bucket, name); notify.success(`Deleted "${name}"`); location.hash = back.slice(1); }}>
        <Typography variant="body2"><b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}
