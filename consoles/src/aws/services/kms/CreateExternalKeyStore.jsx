/* Create external key store — real CreateCustomKeyStore call. Uploading a proxy
 * configuration file is parsed client-side to fill the other fields, exactly like the
 * real console (the upload itself is never sent to a server). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FileUpload from "@cloudscape-design/components/file-upload";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityBadge, saveNotice } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function CreateExternalKeyStore() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [connectivity, setConnectivity] = useState("PUBLIC_ENDPOINT");
  const [endpoint, setEndpoint] = useState("");
  const [pathPrefix, setPathPrefix] = useState("");
  const [accessKeyId, setAccessKeyId] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [files, setFiles] = useState([]);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const parseConfigFile = async (fileList) => {
    setFiles(fileList);
    const f = fileList[0];
    if (!f) return;
    try {
      const cfg = JSON.parse(await f.text());
      if (cfg.UriEndpoint) setEndpoint(cfg.UriEndpoint);
      if (cfg.UriPathPrefix) setPathPrefix(cfg.UriPathPrefix);
    } catch { /* not a JSON config file we recognize; leave fields untouched */ }
  };

  const nameErr = touched && !name ? "Key store name is required." : null;
  const endpointErr = touched && !endpoint ? "Proxy URI endpoint is required." : null;

  const submit = async () => {
    setTouched(true);
    if (!name || !endpoint) return;
    setBusy(true); setError(null);
    try {
      await api.createCustomKeyStore({
        CustomKeyStoreName: name, CustomKeyStoreType: "EXTERNAL_KEY_STORE",
        XksProxyConnectivity: connectivity, XksProxyUriEndpoint: endpoint,
        XksProxyUriPath: pathPrefix || "/kms/xks/v1",
        XksProxyAuthenticationCredential: { AccessKeyId: accessKeyId, RawSecretAccessKey: secretKey },
      });
      notify.success(`Created external key store "${name}".${saveNotice("kms.custom-key-stores")}`);
      navigate("kms", "external-key-stores");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1" actions={<CapabilityBadge id="kms.custom-key-stores" />}>Create external key store</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form errorText={error && <ErrorAlert error={error} />} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href="#/kms/external-key-stores" onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Create external key store</Button>
          </SpaceBetween>
        }>
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Custom key store name</Header>}>
              <FormField label="Key store name" errorText={nameErr} constraintText="Must be unique in your AWS account and Region">
                <Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Key store name" />
              </FormField>
            </Container>
            <Container header={<Header variant="h2">Proxy connectivity</Header>}>
              <SpaceBetween size="l">
                <FormField label="Proxy connectivity">
                  <RadioGroup value={connectivity} onChange={({ detail }) => setConnectivity(detail.value)}
                    items={[{ value: "PUBLIC_ENDPOINT", label: "Public endpoint" }, { value: "VPC_ENDPOINT_SERVICE", label: "VPC endpoint service" }]} />
                </FormField>
                <FormField label="Proxy URI endpoint" errorText={endpointErr} constraintText="10-128 characters; a valid domain starting with https://">
                  <Input value={endpoint} onChange={({ detail }) => setEndpoint(detail.value)} ariaLabel="Proxy URI endpoint" placeholder="https://xks.example.com" />
                </FormField>
              </SpaceBetween>
            </Container>
            <Container header={<Header variant="h2">Proxy configuration</Header>}>
              <SpaceBetween size="l">
                <FormField label="Upload configuration file">
                  <FileUpload value={files} onChange={({ detail }) => parseConfigFile(detail.value)} i18nStrings={{ uploadButtonText: () => "Choose file", removeFileAriaLabel: () => "Remove file", limitShowFewer: "Show fewer", limitShowMore: "Show more" }} showFileLastModified showFileSize tokenLimit={1} />
                </FormField>
                <FormField label="Proxy URI path prefix - optional" constraintText="9-117 characters; a-z, A-Z, 0-9, /, -, _">
                  <Input value={pathPrefix} onChange={({ detail }) => setPathPrefix(detail.value)} placeholder="/kms/xks/v1" ariaLabel="Proxy URI path prefix - optional" />
                </FormField>
                <FormField label="Proxy credential: Access key ID" constraintText="20-30 characters; uppercase A-Z and 2-7">
                  <Input value={accessKeyId} onChange={({ detail }) => setAccessKeyId(detail.value)} ariaLabel="Proxy credential: Access key ID" />
                </FormField>
                <FormField label="Proxy credential: Secret access key" constraintText="43-64 characters; a-z, A-Z, 0-9, /, +, =">
                  <Input type={showSecret ? "text" : "password"} value={secretKey} onChange={({ detail }) => setSecretKey(detail.value)} ariaLabel="Proxy credential: Secret access key" />
                </FormField>
                <Checkbox checked={showSecret} onChange={({ detail }) => setShowSecret(detail.checked)}>Show secret access key</Checkbox>
              </SpaceBetween>
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
