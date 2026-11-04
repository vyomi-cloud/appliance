/* AWS managed key detail — read-only. Title is the Key ID (not the alias), same as the
 * native console: the Aliases list links by alias, the detail route and title use the id. */
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Spinner from "@cloudscape-design/components/spinner";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, fmtDate, KeyValue } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function AwsManagedKeyDetail({ params }) {
  const keyId = params.id;
  const d = useAsync(() => Promise.all([api.describeKey(keyId), api.listAliases(keyId), api.getKeyPolicy(keyId)]), [keyId]);
  if (d.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const [md, aliases, policy] = d.data;
  const alias = aliases[0]?.AliasName?.replace(/^alias\//, "") || "-";
  return (
    <ContentLayout header={<Header variant="h1">{md.KeyId}</Header>}>
      <SpaceBetween size="l">
        <Alert type="info" header="AWS managed keys are read-only">
          AWS creates, manages, and uses this key on your behalf for the service that needs it. You can view its configuration, but you can't manage it.
        </Alert>
        <KeyValue title="General configuration" columns={4} items={[
          ["Alias", alias], ["ARN", md.Arn], ["Current key material ID", md.KeyMaterialId],
          ["Status", md.KeyState], ["Description", md.Description], ["Creation date", fmtDate(md.CreationDate)],
          ["Last used", md.LastUsedDate ? fmtDate(md.LastUsedDate) : "Not used in the last 24 hours"],
          ["Regionality", "Single-Region key"],
        ]} />
        <Tabs tabs={[
          { id: "policy", label: "Key policy", content: (
            <Box variant="code" padding="s"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{policy}</pre></Box>
          ) },
          { id: "crypto", label: "Cryptographic configuration", content: (
            <KeyValue columns={4} items={[
              ["Key Type", "Symmetric"], ["Origin", md.Origin], ["Key Spec", md.KeySpec], ["Key Usage", md.KeyUsage],
            ]} />
          ) },
        ]} />
      </SpaceBetween>
    </ContentLayout>
  );
}
