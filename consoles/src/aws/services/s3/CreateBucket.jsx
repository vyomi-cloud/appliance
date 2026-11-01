/* Create bucket — one long form, like the console. Each section maps to a real S3 call made
 * after CreateBucket; a setting the backend rejects is reported, never silently dropped. */
import { useState } from "react";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Tiles from "@cloudscape-design/components/tiles";
import Checkbox from "@cloudscape-design/components/checkbox";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { TAG_I18N } from "../../kit/tagI18n.js";
import Alert from "@cloudscape-design/components/alert";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import { getRegion } from "../../../common/wire.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const BPA = [
  ["BlockPublicAcls", "Block public access to buckets and objects granted through new access control lists (ACLs)"],
  ["IgnorePublicAcls", "Block public access to buckets and objects granted through any access control lists (ACLs)"],
  ["BlockPublicPolicy", "Block public access to buckets and objects granted through new public bucket or access point policies"],
  ["RestrictPublicBuckets", "Block public and cross-account access to buckets and objects through any public bucket or access point policies"],
];

export const validBucketName = (n) => {
  if (n.length < 3 || n.length > 63) return "Bucket name must be between 3 and 63 characters long.";
  if (!/^[a-z0-9][a-z0-9.-]*[a-z0-9]$/.test(n)) return "Bucket name must contain only lowercase letters, numbers, periods (.), and hyphens (-), and begin and end with a letter or number.";
  if (/\.\./.test(n) || /^\d+\.\d+\.\d+\.\d+$/.test(n)) return "Bucket name must not contain two adjacent periods or be formatted as an IP address.";
  return null;
};

export default function CreateBucket() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [bucketType, setBucketType] = useState("general");
  const [namespace, setNamespace] = useState("global");
  const [ownership, setOwnership] = useState("enforced");
  const [bpa, setBpa] = useState(Object.fromEntries(BPA.map(([k]) => [k, true])));
  const [versioning, setVersioning] = useState("disabled");
  const [tags, setTags] = useState([]);
  const [encType, setEncType] = useState("AES256");
  const [kmsKey, setKmsKey] = useState("");
  const [bucketKey, setBucketKey] = useState("enabled");
  const [objectLock, setObjectLock] = useState("disabled");
  const [objectLockAck, setObjectLockAck] = useState(false);
  const [copyOpen, setCopyOpen] = useState(false);
  const [copyBuckets, setCopyBuckets] = useState(null);
  const [copySource, setCopySource] = useState(null);
  const [copyBusy, setCopyBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const nameErr = touched ? validBucketName(name) : null;
  const allBpa = Object.values(bpa).every(Boolean);

  const openCopySettings = async () => {
    setCopyOpen(true);
    if (!copyBuckets) { try { setCopyBuckets(await api.listBuckets()); } catch { setCopyBuckets([]); } }
  };
  const applyCopySettings = async () => {
    if (!copySource) return;
    setCopyBusy(true);
    try {
      const src = copySource.value;
      const [v, t, e, p] = await Promise.all([api.getVersioning(src), api.getTags(src), api.getEncryption(src), api.getPublicAccessBlock(src)]);
      if (v.status) setVersioning(v.status === "Enabled" ? "enabled" : "disabled");
      if (t.tags) setTags(t.tags.map(({ key, value }) => ({ key, value })));
      if (e.algorithm) { setEncType(e.algorithm); setKmsKey(e.kmsKey || ""); setBucketKey(e.bucketKey ? "enabled" : "disabled"); }
      if (p.config) setBpa(p.config);
      notify.success(`Copied settings from "${src}".`);
      setCopyOpen(false); setCopySource(null);
    } catch (e) { notify.error(e, "Couldn't copy settings"); }
    finally { setCopyBusy(false); }
  };

  const submit = async () => {
    setTouched(true);
    if (validBucketName(name)) return;
    if (objectLock === "enabled" && !objectLockAck) return;
    setBusy(true); setError(null);
    const warnings = [];
    try {
      await api.createBucket(name, { objectLock: objectLock === "enabled" });
      const step = async (label, fn) => { try { await fn(); } catch (e) { warnings.push(`${label}: ${e.message}`); } };
      await step("Block Public Access", () => api.putPublicAccessBlock(name, bpa));
      if (versioning === "enabled" || objectLock === "enabled") await step("Bucket Versioning", () => api.putVersioning(name, true));
      const t = tags.filter((x) => !x.markedForRemoval && x.key).map(({ key, value }) => ({ key, value }));
      if (t.length) await step("Tags", () => api.putTags(name, t));
      await step("Default encryption", () => api.putEncryption(name, encType, encType === "AES256" ? null : kmsKey, encType !== "AES256" && bucketKey === "enabled"));
      notify.success(`Successfully created bucket "${name}"`);
      warnings.forEach((w) => notify.error({ message: w }, "Bucket created, but a setting wasn't applied"));
      navigate("s3", "buckets", name);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1" description="Buckets are containers for data stored in S3.">Create bucket</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button formAction="none" variant="link" href="#/s3" onFollow={follow}>Cancel</Button>
              <Button variant="primary" loading={busy} disabled={objectLock === "enabled" && !objectLockAck}>Create bucket</Button>
            </SpaceBetween>
          }
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">General configuration</Header>}>
              <SpaceBetween size="l">
                <FormField label="AWS Region"><Box>{getRegion()}</Box></FormField>
                <FormField label="Bucket type">
                  <Tiles value={bucketType} onChange={({ detail }) => setBucketType(detail.value)} items={[
                    { value: "general", label: "General purpose", description: "Recommended for most use cases and access patterns." },
                    { value: "directory", label: "Directory", description: "Recommended for low-latency use cases.", disabled: true },
                  ]} />
                </FormField>
                {bucketType === "general" && (
                  <FormField label="Bucket namespace">
                    <RadioGroup value={namespace} onChange={({ detail }) => setNamespace(detail.value)} items={[
                      { value: "global", label: "Global namespace" },
                      { value: "regional", label: "Account Regional namespace (recommended)", disabled: true, description: "Not available in Vyomi yet — buckets use the global namespace." },
                    ]} />
                  </FormField>
                )}
                <FormField label="Bucket name" errorText={nameErr}
                  constraintText="Bucket names must be 3 to 63 characters and unique within the global namespace. Bucket names must also begin and end with a letter or number. Valid characters are a-z, 0-9, periods (.), and hyphens (-).">
                  <Input value={name} placeholder="myawsbucket" onChange={({ detail }) => setName(detail.value)} onBlur={() => setTouched(true)} ariaLabel="Bucket name" />
                </FormField>
                <FormField label="Copy settings from existing bucket" description="Format: s3://bucket/prefix">
                  <Button onClick={openCopySettings}>Choose bucket</Button>
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2" description="Control ownership of objects written to this bucket from other AWS accounts and the use of access control lists (ACLs).">Object Ownership</Header>}>
              <Tiles value={ownership} onChange={({ detail }) => setOwnership(detail.value)} items={[
                { value: "enforced", label: "ACLs disabled (recommended)", description: "All objects in this bucket are owned by this account. Access is specified using only policies." },
                { value: "preferred", label: "ACLs enabled", description: "Objects in this bucket can be owned by other AWS accounts." },
              ]} />
            </Container>

            <Container header={<Header variant="h2">Block Public Access settings for this bucket</Header>}>
              <SpaceBetween size="s">
                <Checkbox checked={allBpa} onChange={({ detail }) => setBpa(Object.fromEntries(BPA.map(([k]) => [k, detail.checked])))}>
                  <b>Block all public access</b>
                </Checkbox>
                <Box padding={{ left: "l" }}>
                  <SpaceBetween size="xs">
                    {BPA.map(([k, label]) => (
                      <Checkbox key={k} checked={bpa[k]} onChange={({ detail }) => setBpa({ ...bpa, [k]: detail.checked })}>{label}</Checkbox>
                    ))}
                  </SpaceBetween>
                </Box>
                {!allBpa && <Alert type="warning">Turning off block all public access might result in this bucket and the objects within becoming public.</Alert>}
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2" description="Versioning is a means of keeping multiple variants of an object in the same bucket.">Bucket Versioning</Header>}>
              <RadioGroup value={versioning} onChange={({ detail }) => setVersioning(detail.value)} items={[{ value: "disabled", label: "Disable" }, { value: "enabled", label: "Enable" }]} />
            </Container>

            <Container header={<Header variant="h2" counter={`(${tags.filter((t) => !t.markedForRemoval).length})`} description="You can use bucket tags to track storage costs and organize buckets.">Tags - optional</Header>}>
              <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} />
            </Container>

            <Container header={<Header variant="h2" description="Server-side encryption is automatically applied to new objects stored in this bucket.">Default encryption</Header>}>
              <SpaceBetween size="l">
                <FormField label="Encryption type">
                  <RadioGroup value={encType} onChange={({ detail }) => setEncType(detail.value)} items={[
                    { value: "AES256", label: "Server-side encryption with Amazon S3 managed keys (SSE-S3)" },
                    { value: "aws:kms", label: "Server-side encryption with AWS Key Management Service keys (SSE-KMS)" },
                    { value: "aws:kms:dsse", label: "Dual-layer server-side encryption with AWS Key Management Service keys (DSSE-KMS)" },
                  ]} />
                </FormField>
                {encType !== "AES256" && (
                  <FormField label="AWS KMS key ARN or key ID" description="Leave empty to use the AWS managed key (aws/s3).">
                    <Input value={kmsKey} onChange={({ detail }) => setKmsKey(detail.value)} placeholder="arn:aws:kms:region:account:key/key-id" />
                  </FormField>
                )}
                <FormField label="Bucket Key">
                  <RadioGroup value={bucketKey} onChange={({ detail }) => setBucketKey(detail.value)} items={[{ value: "disabled", label: "Disable" }, { value: "enabled", label: "Enable" }]} />
                </FormField>
              </SpaceBetween>
            </Container>

            <ExpandableSection headerText="Advanced settings" variant="container">
              <SpaceBetween size="l">
                <FormField label="Object Lock" description="Store objects using a write-once-read-many (WORM) model to help you prevent objects from being deleted or overwritten for a fixed amount of time or indefinitely.">
                  <RadioGroup value={objectLock} onChange={({ detail }) => { setObjectLock(detail.value); if (detail.value === "disabled") setObjectLockAck(false); }} items={[{ value: "disabled", label: "Disable" }, { value: "enabled", label: "Enable", description: "Permanently allows objects in this bucket to be locked. Enabling Object Lock automatically enables Bucket Versioning." }]} />
                </FormField>
                {objectLock === "enabled" && (
                  <Checkbox checked={objectLockAck} onChange={({ detail }) => setObjectLockAck(detail.checked)}>
                    I acknowledge that enabling Object Lock will permanently allow objects in this bucket to be locked.
                  </Checkbox>
                )}
              </SpaceBetween>
            </ExpandableSection>

            <Alert>After creating the bucket, you can upload files and folders to the bucket, and configure additional bucket settings.</Alert>
          </SpaceBetween>
        </Form>
      </form>
      <Modal
        visible={copyOpen}
        onDismiss={() => setCopyOpen(false)}
        header="Copy settings from existing bucket"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCopyOpen(false)}>Cancel</Button>
          <Button variant="primary" loading={copyBusy} disabled={!copySource} onClick={applyCopySettings}>Choose bucket</Button>
        </SpaceBetween></Box>}
      >
        <FormField label="Bucket" description="Versioning, tags, default encryption, and Block Public Access are copied onto this new bucket.">
          <Select
            selectedOption={copySource}
            onChange={({ detail }) => setCopySource(detail.selectedOption)}
            options={(copyBuckets || []).map((b) => ({ value: b.name, label: b.name }))}
            loadingText="Loading buckets"
            statusType={copyBuckets ? "finished" : "loading"}
            placeholder="Choose a bucket"
            empty="No buckets to copy settings from"
          />
        </FormField>
      </Modal>
    </ContentLayout>
  );
}
