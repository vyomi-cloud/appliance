import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const ENGINE_TYPES = ["Aurora MySQL", "Aurora PostgreSQL", "MySQL Community", "PostgreSQL", "MariaDB", "Oracle", "SQL Server", "Db2"];
const FAMILIES_BY_ENGINE = {
  "Aurora MySQL": ["aurora-mysql5.7", "aurora-mysql8.0"],
  "Aurora PostgreSQL": ["aurora-postgresql14", "aurora-postgresql15", "aurora-postgresql16"],
  "MySQL Community": ["mysql5.7", "mysql8.0"],
  "PostgreSQL": ["postgres14", "postgres15", "postgres16"],
  "MariaDB": ["mariadb10.6", "mariadb10.11"],
  "Oracle": ["oracle-ee-19"],
  "SQL Server": ["sqlserver-ee-16.0"],
  "Db2": ["db2-ee-11.5"],
};

export default function CreateParameterGroup() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [engineType, setEngineType] = useState("Aurora MySQL");
  const [family, setFamily] = useState(FAMILIES_BY_ENGINE["Aurora MySQL"][0]);
  const [type, setType] = useState("DB Parameter Group");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const g = await api.createDBParameterGroup(name, family, description, type);
      notify.success(`Parameter group "${g.DBParameterGroupName}" created.`);
      navigate("rds", "parameter-groups");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create parameter group</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form errorText={error && <ErrorAlert error={error} />} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href={href("rds", "parameter-groups")} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!name || !description}>Create</Button>
          </SpaceBetween>
        }>
          <Container header={<Header variant="h2">Parameter group details</Header>}>
            <SpaceBetween size="l">
              <FormField label="Parameter group name" constraintText="1 to 255 characters, begin with a letter; can't end with a hyphen or contain two consecutive hyphens">
                <Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Parameter group name" />
              </FormField>
              <FormField label="Description" description="This description appears in the Parameter groups dashboard.">
                <Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" />
              </FormField>
              <FormField label="Engine type">
                <Select selectedOption={{ value: engineType, label: engineType }} onChange={({ detail }) => {
                  setEngineType(detail.selectedOption.value); setFamily(FAMILIES_BY_ENGINE[detail.selectedOption.value][0]);
                }} options={ENGINE_TYPES.map((v) => ({ value: v, label: v }))} ariaLabel="Engine type" />
              </FormField>
              <FormField label="Parameter group family">
                <Select selectedOption={{ value: family, label: family }} onChange={({ detail }) => setFamily(detail.selectedOption.value)}
                  options={FAMILIES_BY_ENGINE[engineType].map((v) => ({ value: v, label: v }))} ariaLabel="Parameter group family" />
              </FormField>
              <FormField label="Type">
                <Select selectedOption={{ value: type, label: type }} onChange={({ detail }) => setType(detail.selectedOption.value)}
                  options={["DB Parameter Group", "DB Cluster Parameter Group"].map((v) => ({ value: v, label: v }))} ariaLabel="Type" />
              </FormField>
            </SpaceBetween>
          </Container>
        </Form>
      </form>
    </ContentLayout>
  );
}
