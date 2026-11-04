/* Edit secret value — its own page, like the console's modal. Loads the current value so
 * the Key/value tab round-trips a JSON object correctly instead of clobbering it. */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import KeyValueOrPlaintext from "./KeyValueOrPlaintext.jsx";
import * as api from "./api.js";

export default function EditSecretValuePage({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("keyvalue");
  const [pairs, setPairs] = useState([{ key: "", value: "" }]);
  const [plaintext, setPlaintext] = useState("");
  const v = useAsync(async () => {
    const r = await api.getSecretValue(name);
    const kv = api.asKeyValue(r.SecretString);
    if (kv) { setPairs(kv.length ? kv : [{ key: "", value: "" }]); setTab("keyvalue"); }
    else { setPlaintext(r.SecretString ?? ""); setTab("plaintext"); }
    return r;
  }, [name]);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const value = tab === "plaintext" ? plaintext : JSON.stringify(Object.fromEntries(pairs.filter((p) => p.key).map((p) => [p.key, p.value])));
      await api.putSecretValue(name, { SecretString: value });
      notify.success(`Successfully updated the value for "${name}".`);
      navigate("secretsmanager", "secret", name);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  if (v.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;

  return (
    <ContentLayout header={<Header variant="h1">Edit secret value</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Edit secret value</Header>}>
          <SpaceBetween size="m">
            {error && <ErrorAlert error={error} />}
            <KeyValueOrPlaintext tab={tab} setTab={setTab} pairs={pairs} setPairs={setPairs} plaintext={plaintext} setPlaintext={setPlaintext} />
          </SpaceBetween>
        </Container>
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" href={href("secretsmanager", "secret", name)} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy} onClick={submit}>Save</Button>
          </SpaceBetween>
        </Box>
      </SpaceBetween>
    </ContentLayout>
  );
}
