/* Marketplace deployments: registered endpoints, METADATA ONLY (no SageMaker endpoint is created). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import DeleteModal from "../../../kit/DeleteModal.jsx";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import { navigate } from "../../../../common/router.js";
import * as api from "./api.js";
import { CreateModal, Field, HowItWorks, Page, jobStatus, when } from "./Shared.jsx";

export default function MarketplaceDeployments() {
  const notify = useNotify();
  const t = useAsync(() => api.listEndpoints(), []);
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false), [del, setDel] = useState(false);
  const [arn, setArn] = useState(""), [src, setSrc] = useState("");
  const catalog = () => navigate("bedrock", "models");
  const cta = <Button variant="primary" onClick={catalog}>View marketplace models</Button>;
  return (
    <Page title="Marketplace deployments" description="A list of deployed endpoints.">
      <HowItWorks steps={[
        { title: "Discover", body: "Find the model you need in the model catalog.", action: <Button onClick={catalog}>View model catalog</Button> },
        { title: "Subscribe and deploy", body: "For Marketplace models, subscribe to a model from the model catalog. Once a model is subscribed, you can deploy one or more endpoints." },
        { title: "Manage", body: "View and scale your Marketplace deployments based on usage. You can also register existing SageMaker endpoints in Bedrock." },
      ]} />
      <ResourceTable variant="container" resourceName="Managed deployments" description="This is a list of deployed endpoints that are available in Bedrock." items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload}
        trackBy="endpointArn" selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Find endpoints"
        actions={<>
          <ButtonDropdown items={[{ id: "register", text: "Register endpoint" }, { id: "dereg", text: "Deregister endpoint", disabled: !sel.length }]}
            onItemClick={async ({ detail }) => { if (detail.id === "register") setOpen(true); else { await api.deregisterEndpoint(sel[0].endpointArn); t.reload(); } }}>Registration</ButtonDropdown>
          <Button disabled>Edit</Button><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button><Button disabled>Open in playground</Button></>}
        empty={{ title: "No deployments", subtitle: <>Use the model catalog to subscribe and deploy models. Once deployed, those endpoints will be displayed here. You can also <Link onFollow={() => setOpen(true)}>register endpoints</Link> from SageMaker.</>, action: cta }}
        columns={[
          { id: "model", header: "Model ...", isRowHeader: true, cell: (e) => e.modelSourceIdentifier },
          { id: "name", header: "Endpoi...", cell: (e) => e.endpointArn.split("/").pop() },
          { id: "status", header: "Endpoi...", cell: (e) => jobStatus(e.status === "Registered" ? "InService" : e.status) },
          { id: "reg", header: "Registr...", cell: (e) => e.status },
          { id: "arn", header: "Endpoint ARN", cell: (e) => e.endpointArn },
          { id: "marn", header: "Model ARN", cell: (e) => e.modelSourceIdentifier },
          { id: "date", header: "Date deployed", sortingField: "createdAt", cell: (e) => when(e.createdAt) },
        ]} />
      <CreateModal visible={open} onDismiss={() => setOpen(false)} header="Register SageMaker endpoint" submitLabel="Register" disabled={!arn || !src}
        onSubmit={async () => { await api.registerEndpoint(arn, src); notify.success("Endpoint registered (metadata only: Vyomi does not create SageMaker endpoints)."); t.reload(); }}>
        <Field label="SageMaker endpoint ARN" placeholder="arn:aws:sagemaker:us-east-1:123456789012:endpoint/my-endpoint" value={arn} onChange={setArn} />
        <Field label="Model source identifier" value={src} onChange={setSrc} />
      </CreateModal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="endpoint" names={sel.map((e) => e.endpointArn.split("/").pop())} onConfirm={async () => { await api.deleteEndpoint(sel[0].endpointArn); setSel([]); t.reload(); }} />
    </Page>
  );
}
