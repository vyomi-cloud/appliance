import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Multiselect from "@cloudscape-design/components/multiselect";
import Table from "@cloudscape-design/components/table";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { AZS } from "./engines.js";
import * as api from "./api.js";

const SUBNETS_BY_AZ = {
  "us-east-1a": [{ value: "subnet-0a1a1a1a", label: "subnet-0a1a1a1a" }],
  "us-east-1b": [{ value: "subnet-0b1b1b1b", label: "subnet-0b1b1b1b" }],
  "us-east-1c": [{ value: "subnet-0c1c1c1c", label: "subnet-0c1c1c1c" }],
};

export default function CreateSubnetGroup() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [vpc, setVpc] = useState({ value: "vpc-default", label: "Default VPC (vpc-default)" });
  const [az, setAz] = useState(null);
  const [subnets, setSubnets] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const addSubnets = (selected) => {
    const rows = selected.map((o) => ({ az: az?.value, subnetId: o.value, cidr: "10.0.0.0/24" }));
    setSubnets((s) => [...s, ...rows.filter((r) => !s.some((x) => x.subnetId === r.subnetId))]);
  };

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const g = await api.createDBSubnetGroup(name, description, vpc.value, subnets.map((s) => s.subnetId));
      notify.success(`DB subnet group "${g.DBSubnetGroupName}" created.`);
      navigate("rds", "subnet-groups");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create DB subnet group</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form errorText={error && <ErrorAlert error={error} />} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href={href("rds", "subnet-groups")} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!name || !description || !subnets.length}>Create</Button>
          </SpaceBetween>
        }>
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Subnet group details</Header>}>
              <SpaceBetween size="l">
                <FormField label="Name" constraintText="1 to 255 characters; letters, numbers, spaces, '.', '_', '-'">
                  <Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" />
                </FormField>
                <FormField label="Description">
                  <Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" />
                </FormField>
                <FormField label="VPC">
                  <Select selectedOption={vpc} onChange={({ detail }) => setVpc(detail.selectedOption)} placeholder="Choose a VPC"
                    options={[{ value: "vpc-default", label: "Default VPC (vpc-default)" }]} ariaLabel="VPC" />
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Add subnets</Header>}>
              <SpaceBetween size="l">
                <FormField label="Availability Zones">
                  <Select selectedOption={az} onChange={({ detail }) => setAz(detail.selectedOption)} placeholder="Choose an availability zone"
                    options={AZS.map((a) => ({ value: a, label: a }))} ariaLabel="Availability Zones" />
                </FormField>
                <FormField label="Subnets">
                  <Multiselect selectedOptions={[]} onChange={({ detail }) => addSubnets(detail.selectedOptions)} placeholder="Select subnets"
                    disabled={!az} options={SUBNETS_BY_AZ[az?.value] || []} ariaLabel="Subnets" />
                </FormField>
              </SpaceBetween>
            </Container>

            <Table variant="container" items={subnets} trackBy="subnetId"
              header={<Header variant="h2" counter={`(${subnets.length})`}>Subnets selected</Header>}
              columnDefinitions={[
                { id: "az", header: "Availability zone", cell: (s) => s.az },
                { id: "id", header: "Subnet ID", cell: (s) => s.subnetId },
                { id: "cidr", header: "CIDR block", cell: (s) => s.cidr },
              ]}
              empty={<Box textAlign="center" color="inherit"><b>No subnets selected</b></Box>} />
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
