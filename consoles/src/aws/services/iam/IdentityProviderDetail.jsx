/* Identity provider detail (OIDC / SAML): OIDC client IDs add/remove + thumbprints replace, SAML metadata
 * update, tags - real IAM API calls (AddClientIDToOpenIDConnectProvider, UpdateOpenIDConnectProviderThumbprint,
 * UpdateSAMLProvider, Tag/Untag/List...ProviderTags). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { asList } from "../../../common/wire.js";
import { ErrorAlert, KeyValue, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function IdentityProviderDetail({ params }) {
  const notify = useNotify();
  const kind = params.kind === "saml" ? "SAML" : "OpenIDConnect";
  const arn = decodeURIComponent(params.arn).replace(/~/g, "/");   // "/" travels as "~" in the route
  const d = useAsync(async () => {
    const [p, tags] = await Promise.all([kind === "SAML" ? api.getSamlProvider(arn) : api.getOidcProvider(arn), api.listProviderTags(kind, arn)]);
    return { p, tags };
  }, [arn]);
  const [clientId, setClientId] = useState("");
  const [thumbs, setThumbs] = useState(null);
  const [meta, setMeta] = useState(null);
  const [tag, setTag] = useState({ key: "", value: "" });
  if (d.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const { p, tags } = d.data;
  const act = async (fn, msg) => { try { await fn(); notify.success(msg); d.reload(); } catch (e) { notify.error(e); } };
  const clientIds = asList(p.ClientIDList?.member);
  const thumbprints = asList(p.ThumbprintList?.member);

  return (
    <ContentLayout header={<Header variant="h1">{arn.split("/").slice(1).join("/")}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Summary" columns={3} items={[
          ["ARN", arn], ["Type", kind === "SAML" ? "SAML" : "OpenID Connect"], ["Creation time", fmtDate(p.CreateDate)],
          ...(kind === "SAML" ? [] : [["Provider URL", p.Url]]),
        ]} />
        {kind === "OpenIDConnect" && (
          <>
            <CapabilityContainer id="iam.identity-providers" title="Audiences (client IDs)" counter={`(${clientIds.length})`}
              actions={<SpaceBetween direction="horizontal" size="xs">
                <Input value={clientId} onChange={({ detail }) => setClientId(detail.value)} placeholder="client ID" ariaLabel="Client ID" />
                <Button disabled={!clientId} onClick={() => act(async () => { await api.addOidcClientId(arn, clientId); setClientId(""); }, "Audience added.")}>Add audience</Button>
              </SpaceBetween>}>
              <Table variant="embedded" items={clientIds.map((c) => ({ c }))} trackBy="c"
                columnDefinitions={[
                  { id: "c", header: "Audience", isRowHeader: true, cell: (x) => x.c },
                  { id: "a", header: "Actions", cell: (x) => <Button variant="inline-link" onClick={() => act(() => api.removeOidcClientId(arn, x.c), "Audience removed.")}>Remove</Button> },
                ]}
                empty={<Box textAlign="center"><b>No audiences</b></Box>} />
            </CapabilityContainer>
            <CapabilityContainer id="iam.identity-providers" title="Thumbprints" counter={`(${thumbprints.length})`}
              actions={thumbs === null
                ? <Button onClick={() => setThumbs(thumbprints.join("\n"))}>Edit thumbprints</Button>
                : <Button variant="primary" onClick={() => act(async () => { await api.updateOidcThumbprints(arn, thumbs.split(/\s+/).filter(Boolean)); setThumbs(null); }, "Thumbprints updated.")}>Save thumbprints</Button>}>
              {thumbs === null
                ? <Box variant="code">{thumbprints.join(", ") || "-"}</Box>
                : <Textarea rows={5} value={thumbs} onChange={({ detail }) => setThumbs(detail.value)} ariaLabel="Thumbprints" spellcheck={false} />}
            </CapabilityContainer>
          </>
        )}
        {kind === "SAML" && (
          <CapabilityContainer id="iam.identity-providers" title="Metadata document"
            actions={meta === null
              ? <Button onClick={() => setMeta(p.SAMLMetadataDocument || "")}>Update metadata</Button>
              : <Button variant="primary" onClick={() => act(async () => { await api.updateSamlProvider(arn, meta); setMeta(null); }, "Metadata updated.")}>Save metadata</Button>}>
            {meta === null
              ? <Box variant="code" fontSize="body-s"><pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{p.SAMLMetadataDocument}</pre></Box>
              : <Textarea rows={10} value={meta} onChange={({ detail }) => setMeta(detail.value)} ariaLabel="Metadata document" spellcheck={false} />}
          </CapabilityContainer>
        )}
        <CapabilityContainer id="iam.identity-providers" title="Tags" counter={`(${tags.length})`}
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Input value={tag.key} onChange={({ detail }) => setTag((t) => ({ ...t, key: detail.value }))} placeholder="Key" ariaLabel="Tag key" />
            <Input value={tag.value} onChange={({ detail }) => setTag((t) => ({ ...t, value: detail.value }))} placeholder="Value" ariaLabel="Tag value" />
            <Button disabled={!tag.key} onClick={() => act(async () => { await api.tagProvider(kind, arn, [{ key: tag.key, value: tag.value }]); setTag({ key: "", value: "" }); }, "Tag added.")}>Add tag</Button>
          </SpaceBetween>}>
          <Table variant="embedded" items={tags} trackBy="Key"
            columnDefinitions={[
              { id: "k", header: "Key", isRowHeader: true, cell: (t) => t.Key }, { id: "v", header: "Value", cell: (t) => t.Value || "-" },
              { id: "a", header: "Actions", cell: (t) => <Button variant="inline-link" onClick={() => act(() => api.untagProvider(kind, arn, [t.Key]), "Tag removed.")}>Remove</Button> },
            ]}
            empty={<Box textAlign="center"><b>No tags</b></Box>} />
        </CapabilityContainer>
      </SpaceBetween>
    </ContentLayout>
  );
}
