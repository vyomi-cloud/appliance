/* Upload — its own page, like the real console (not a modal). Every row becomes a real
 * PutObject; "Permissions" sends the canned ACL as x-amz-acl, which the backend enforces
 * (Object Ownership / Block Public Access) and stores as the object's ACL. */
import { useRef, useState } from "react";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import Table from "@cloudscape-design/components/table";
import FormField from "@cloudscape-design/components/form-field";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import Form from "@cloudscape-design/components/form";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { ErrorAlert, fmtBytes } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const CANNED_ACLS = [
  ["private", "Private (default) - only the object owner has access"],
  ["public-read", "Grant public-read - Everyone (public access) can read the object"],
  ["public-read-write", "Grant public-read-write - Everyone (public access) can read and write the object"],
  ["authenticated-read", "Grant authenticated-read - Authenticated users group can read the object"],
  ["bucket-owner-read", "Grant bucket-owner-read - the bucket owner can read the object"],
  ["bucket-owner-full-control", "Grant bucket-owner-full-control - the bucket owner has full control"],
];
const STORAGE_CLASSES = ["Standard", "Intelligent-Tiering", "Standard-IA", "One Zone-IA", "Glacier Instant Retrieval", "Glacier Flexible Retrieval", "Glacier Deep Archive", "Reduced redundancy"];

export default function UploadPage({ params, query }) {
  const bucket = params.bucket;
  const prefix = query.prefix || "";
  const notify = useNotify();
  const fileInput = useRef(null);
  const folderInput = useRef(null);
  const [rows, setRows] = useState([]);
  const [sel, setSel] = useState([]);
  const [storageClass, setStorageClass] = useState("Standard");
  const [checksumAlgo, setChecksumAlgo] = useState("");
  const [acl, setAcl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const addFiles = (fileList) => {
    const added = [...fileList].map((f) => ({ key: (f.webkitRelativePath || f.name), file: f }));
    setRows((r) => [...r, ...added.filter((a) => !r.some((x) => x.key === a.key))]);
  };

  const submit = async () => {
    if (!rows.length) return;
    setBusy(true); setError(null);
    try {
      for (const r of rows) {
        await api.putObject(bucket, prefix + r.key, r.file, r.file.type, { "x-amz-storage-class": storageClass.toUpperCase().replace(/[ -]/g, "_"), ...(checksumAlgo ? { "x-amz-sdk-checksum-algorithm": checksumAlgo } : {}), ...(acl ? { "x-amz-acl": acl } : {}) });
      }
      notify.success(`Successfully uploaded ${rows.length} file${rows.length === 1 ? "" : "s"} to ${bucket}`);
      location.hash = `${href("s3", "buckets", bucket).slice(1)}${prefix ? `?prefix=${encodeURIComponent(prefix)}` : ""}`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1" description={`s3://${bucket}/${prefix}`}>Upload</Header>}>
      <input ref={fileInput} type="file" multiple hidden onChange={(e) => { if (e.target.files.length) addFiles(e.target.files); e.target.value = ""; }} />
      <input ref={folderInput} type="file" multiple webkitdirectory="" hidden onChange={(e) => { if (e.target.files.length) addFiles(e.target.files); e.target.value = ""; }} />
      <Form
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" href={href("s3", "buckets", bucket)} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!rows.length} onClick={submit}>Upload</Button>
          </SpaceBetween>
        }
        errorText={error && <ErrorAlert error={error} />}
      >
        <SpaceBetween size="l">
          <Table
            variant="container"
            header={<Header variant="h2" counter={`(${rows.length})`}
              actions={<SpaceBetween direction="horizontal" size="xs">
                <Button disabled={!sel.length} onClick={() => { setRows((r) => r.filter((x) => !sel.includes(x))); setSel([]); }}>Remove</Button>
                <Button onClick={() => fileInput.current?.click()}>Add files</Button>
                <Button onClick={() => folderInput.current?.click()}>Add folder</Button>
              </SpaceBetween>}
            >Files and folders</Header>}
            items={rows}
            trackBy="key"
            selectionType="multi"
            selectedItems={sel}
            onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
            columnDefinitions={[
              { id: "name", header: "Name", cell: (r) => r.key },
              { id: "folder", header: "Folder", cell: (r) => r.key.includes("/") ? r.key.slice(0, r.key.lastIndexOf("/") + 1) : "-" },
              { id: "type", header: "Type", cell: (r) => r.file.name.includes(".") ? r.file.name.split(".").pop() : "-" },
              { id: "size", header: "Size", cell: (r) => fmtBytes(r.file.size) },
            ]}
            empty={<Box textAlign="center" color="inherit"><b>No files or folders</b><Box variant="p" color="inherit">Add files or a folder to upload.</Box></Box>}
          />
          <Container header={<Header variant="h2">Destination</Header>}>
            <FormField label="Destination"><Box>{`s3://${bucket}/${prefix}`}</Box></FormField>
          </Container>
          <CapabilityContainer id="s3.object.upload-acl" title="Permissions" description="Grant access to the objects being uploaded. Buckets with ACLs disabled (Bucket owner enforced) only accept bucket-owner-full-control.">
            <FormField label="Access control list (ACL)">
              <RadioGroup value={acl} onChange={({ detail }) => setAcl(detail.value)}
                items={[{ value: "", label: "Use the bucket's default (no ACL sent)" }, ...CANNED_ACLS.map(([value, label]) => ({ value, label }))]} />
            </FormField>
          </CapabilityContainer>
          <Container header={<Header variant="h2">Properties</Header>}>
            <FormField label="Storage class">
              <RadioGroup value={storageClass} onChange={({ detail }) => setStorageClass(detail.value)} items={STORAGE_CLASSES.map((v) => ({ value: v, label: v }))} />
            </FormField>
          </Container>
          <Container header={<Header variant="h2">Additional checksums</Header>}>
            <FormField label="Checksum function" description="The server computes and stores the checksum with each uploaded object.">
              <RadioGroup value={checksumAlgo} onChange={({ detail }) => setChecksumAlgo(detail.value)} items={api.CHECKSUM_ALGOS.map(([value, label]) => ({ value, label }))} />
            </FormField>
          </Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}
