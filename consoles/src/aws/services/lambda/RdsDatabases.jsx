/* Lambda > Configuration > RDS databases: proxies in this function's VPC + the "Connect to RDS database" helper that creates an
 * RDS Proxy (real CreateDBProxy + RegisterDBProxyTargets) in the function's subnets/security groups. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Alert from "@cloudscape-design/components/alert";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const FAMILY = { postgres: "POSTGRESQL", "aurora-postgresql": "POSTGRESQL", mysql: "MYSQL", mariadb: "MYSQL", "aurora-mysql": "MYSQL" };
const asArr = (m) => (m ? [].concat(m) : []);

export default function RdsDatabases({ fn, cfg }) {
  const notify = useNotify();
  const subnets = cfg.VpcConfig?.SubnetIds || [];
  const sgs = cfg.VpcConfig?.SecurityGroupIds || [];
  const proxies = useAsync(async () => {
    const all = await api.rdsListProxies();
    const mine = all.filter((p) => asArr(p.VpcSubnetIds?.member).some((s) => subnets.includes(s)));
    return Promise.all(mine.map(async (p) => ({ ...p, targets: await api.rdsProxyTargets(p.DBProxyName).catch(() => []) })));
  }, [fn, subnets.join(",")]);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ db: "", secret: "", role: "", name: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const dbs = useAsync(() => (open ? api.rdsListInstances() : Promise.resolve([])), [open]);
  const secrets = useAsync(() => (open ? api.rdsListSecrets() : Promise.resolve([])), [open]);
  const roles = useAsync(() => (open ? api.rdsListRoles() : Promise.resolve([])), [open]);
  const inst = (dbs.data || []).find((d) => d.DBInstanceIdentifier === f.db);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.connectToRds({ proxyName: f.name, family: FAMILY[inst?.Engine] || "POSTGRESQL", roleArn: f.role, secretArn: f.secret, dbId: f.db, subnets, securityGroups: sgs });
      notify.success(`RDS Proxy ${f.name} created and ${f.db} registered as its target.`); setOpen(false); proxies.reload();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const canConnect = subnets.length >= 2 && sgs.length >= 1;
  return (
    <CapabilityContainer id="lambda.function.rds-databases" title="RDS databases" actions={<Button disabled={!canConnect} onClick={() => { setF({ db: "", secret: "", role: "", name: `${fn}-proxy` }); setOpen(true); }}>Connect to RDS database</Button>}>
      <SpaceBetween size="m">
        {!canConnect && <Alert type="info">Attach this function to a VPC with at least two subnets and one security group (VPC section above) to connect it to an RDS database through a proxy.</Alert>}
        <Table variant="embedded" loading={proxies.loading} items={proxies.data || []} trackBy="DBProxyName"
          columnDefinitions={[
            { id: "p", header: "Proxy", cell: (p) => p.DBProxyName },
            { id: "e", header: "Proxy endpoint", cell: (p) => p.Endpoint || "-" },
            { id: "d", header: "Target database", cell: (p) => p.targets.map((t) => t.RdsResourceId).join(", ") || "-" },
            { id: "a", header: "", cell: (p) => <Button variant="inline-link" onClick={async () => { await api.rdsDeleteProxy(p.DBProxyName); proxies.reload(); }}>Delete proxy</Button> },
          ]} empty={<Box textAlign="center" color="inherit"><b>No RDS databases connected</b></Box>} />
      </SpaceBetween>
      <Modal visible={open} onDismiss={() => setOpen(false)} header="Connect to RDS database"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" loading={busy} disabled={!f.db || !f.secret || !f.role || !f.name} onClick={submit}>Create proxy</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {error && <ErrorAlert error={error} />}
          <FormField label="Proxy name"><Input ariaLabel="Proxy name" value={f.name} onChange={({ detail }) => setF({ ...f, name: detail.value })} /></FormField>
          <FormField label="RDS database" description="The proxy is created in this function's subnets and security groups."><Select ariaLabel="RDS database" selectedOption={f.db ? { value: f.db, label: f.db } : null} placeholder="Choose a database"
            options={(dbs.data || []).map((d) => ({ value: d.DBInstanceIdentifier, label: d.DBInstanceIdentifier, description: d.Engine }))} onChange={({ detail }) => setF({ ...f, db: detail.selectedOption.value })} statusType={dbs.loading ? "loading" : "finished"} /></FormField>
          <FormField label="Secrets Manager secret (database credentials)"><Select ariaLabel="Secret" selectedOption={f.secret ? { value: f.secret, label: f.secret.split(":secret:")[1] || f.secret } : null} placeholder="Choose a secret"
            options={(secrets.data || []).map((s) => ({ value: s.ARN, label: s.Name }))} onChange={({ detail }) => setF({ ...f, secret: detail.selectedOption.value })} statusType={secrets.loading ? "loading" : "finished"} /></FormField>
          <FormField label="IAM role" description="Lets the proxy read the secret."><Select ariaLabel="IAM role" selectedOption={f.role ? { value: f.role, label: f.role.split("/").pop() } : null} placeholder="Choose a role"
            options={(roles.data || []).map((r) => ({ value: r.arn, label: r.name }))} onChange={({ detail }) => setF({ ...f, role: detail.selectedOption.value })} statusType={roles.loading ? "loading" : "finished"} /></FormField>
        </SpaceBetween>
      </Modal>
    </CapabilityContainer>
  );
}
