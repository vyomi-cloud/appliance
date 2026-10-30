import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Checkbox from "@cloudscape-design/components/checkbox";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import Box from "@cloudscape-design/components/box";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, NotSimulated } from "../../kit/common.jsx";
import { AZS, ENGINES, ENGINE_VERSIONS, ENGINE_WIRE, INSTANCE_CLASSES, isAurora } from "./engines.js";
import * as api from "./api.js";

const opt = (v) => ({ value: v, label: v });
const SELECT = (v) => (v ? { value: v, label: v } : null);

export default function CreateDatabase() {
  const notify = useNotify();
  const [f, setF] = useState({
    method: "Full configuration",
    engineLabel: "Aurora (PostgreSQL Compatible)",
    engineVersion: ENGINE_VERSIONS["aurora-postgresql"][0],
    template: "Production",
    freeTier: "No",
    scalability: "Provisioned",
    deployment: "Single-AZ DB instance deployment (1 instance)",
    clusterId: "database-1-cluster",
    instanceId: "database-1",
    masterUsername: "postgres",
    credMgmt: "Managed in AWS Secrets Manager",
    encKey: "aws/secretsmanager (default)",
    autoGenPw: false,
    masterPw: "",
    confirmPw: "",
    provisionedType: "Memory optimized classes (includes r classes)",
    instanceClass: "db.r7g.large",
    storageType: "General Purpose SSD (gp3)",
    allocatedStorage: "20",
    storageAutoscale: true,
    maxStorage: "1000",
    clusterStorageConfig: "Aurora I/O-Optimized",
    multiAzDeployment: "Create an Aurora Replica or Reader node in a different AZ (recommended for scaled availability)",
    computeResource: "Don't connect to an EC2 compute resource",
    networkType: "IPv4",
    vpc: "Default VPC",
    subnetGroup: "default",
    publicAccess: "No",
    sgChoice: "Choose existing",
    existingSgs: "default",
    newSgName: "",
    az: "No preference",
    rdsProxy: false,
    ca: "",
    port: "5432",
    capRes: "No capacity reservation",
    capResReplica: "No capacity reservation",
    tags: [],
    iamFeature: "",
    iamRole: "",
    babelfish: false,
    dbInsights: "Database Insights - Standard",
    detailedMetrics: true,
    retentionPeriod: "7 days (free)",
    kmsKey: "(default) aws/rds",
    initialDbName: "",
    paramGroup: "default",
    optionGroup: "",
    autoBackups: true,
    backupRetention: "7 days",
    backupWindow: "No preference",
    copyTagsToSnapshots: true,
    enableEncryption: true,
    logExports: false,
    autoMinorUpgrade: true,
    maintenanceWindow: "No preference",
    deletionProtection: true,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (v) => setF((s) => ({ ...s, [k]: v }));
  const engineWire = ENGINE_WIRE[f.engineLabel];
  const aurora = isAurora(f.engineLabel);
  const dbId = aurora ? f.clusterId : f.instanceId;

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const created = await api.createDBInstance({
        DBInstanceIdentifier: dbId,
        Engine: engineWire,
        EngineVersion: f.engineVersion,
        DBInstanceClass: f.instanceClass,
        MasterUsername: f.masterUsername,
        MasterUserPassword: f.credMgmt === "Self managed" ? f.masterPw : "managed-by-secrets-manager",
        AllocatedStorage: f.allocatedStorage,
        StorageType: f.storageType,
        MultiAZ: String(f.multiAzDeployment.startsWith("Create") || f.deployment.startsWith("Multi")),
        PubliclyAccessible: String(f.publicAccess === "Yes"),
        DBSubnetGroupName: f.subnetGroup,
        Port: f.port,
        BackupRetentionPeriod: f.autoBackups ? parseInt(f.backupRetention) || 7 : 0,
        DeletionProtection: String(f.deletionProtection),
      }, f.tags.filter((t) => t.key).map((t) => ({ Key: t.key, Value: t.value || "" })));
      notify.success(`Creating database "${created.DBInstanceIdentifier}". It will be available for use shortly.`);
      navigate("rds", "databases", created.DBInstanceIdentifier);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create database</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form errorText={error && <ErrorAlert error={error} />} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href={href("rds", "databases")} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Create database</Button>
          </SpaceBetween>
        }>
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Choose a database creation method</Header>}>
              <FormField label="Database creation method">
                <RadioGroup value={f.method} onChange={({ detail }) => set("method")(detail.value)}
                  items={["Full configuration", "Express configuration"].map((v) => opt(v))} />
              </FormField>
            </Container>

            <Container header={<Header variant="h2">Engine options</Header>}>
              <SpaceBetween size="l">
                <FormField label="Engine type">
                  <RadioGroup value={f.engineLabel} onChange={({ detail }) => {
                    const wire = ENGINE_WIRE[detail.value];
                    setF((s) => ({ ...s, engineLabel: detail.value, engineVersion: ENGINE_VERSIONS[wire][0] }));
                  }} items={ENGINES.map((v) => opt(v))} />
                </FormField>
                <FormField label="Engine version" description="View the engine versions based on your selected database and cluster scalability type.">
                  <Select selectedOption={SELECT(f.engineVersion)} onChange={({ detail }) => set("engineVersion")(detail.selectedOption.value)}
                    placeholder="Choose an engine version" options={(ENGINE_VERSIONS[engineWire] || []).map((v) => opt(v))} ariaLabel="Engine version" />
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Templates</Header>}>
              <SpaceBetween size="l">
                <FormField label="Templates" description="Choose a sample template to meet your use case.">
                  <RadioGroup value={f.template} onChange={({ detail }) => set("template")(detail.value)} items={["Production", "Dev/Test"].map((v) => opt(v))} />
                </FormField>
                <FormField label="Free tier">
                  <RadioGroup value={f.freeTier} onChange={({ detail }) => set("freeTier")(detail.value)} items={["Yes", "No"].map((v) => opt(v))} />
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Cluster scalability type</Header>}>
              <FormField label="Cluster scalability type">
                <RadioGroup value={f.scalability} onChange={({ detail }) => set("scalability")(detail.value)}
                  items={["Aurora serverless", "Limitless Database", "Provisioned"].map((v) => opt(v))} />
              </FormField>
            </Container>

            <Container header={<Header variant="h2">Availability and durability</Header>}>
              <FormField label="Deployment options">
                <RadioGroup value={f.deployment} onChange={({ detail }) => set("deployment")(detail.value)}
                  items={["Multi-AZ DB cluster deployment (3 instances)", "Multi-AZ DB instance deployment (2 instances)", "Single-AZ DB instance deployment (1 instance)"].map((v) => opt(v))} />
              </FormField>
            </Container>

            <Container header={<Header variant="h2">Settings</Header>}>
              <SpaceBetween size="l">
                <FormField label="DB cluster identifier" constraintText="1 to 63 alphanumeric characters or hyphens. First character must be a letter.">
                  <Input value={f.clusterId} onChange={({ detail }) => set("clusterId")(detail.value)} ariaLabel="DB cluster identifier" />
                </FormField>
                <FormField label="DB instance identifier" constraintText="1 to 63 alphanumeric characters or hyphens. First character must be a letter.">
                  <Input value={f.instanceId} onChange={({ detail }) => set("instanceId")(detail.value)} ariaLabel="DB instance identifier" />
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Credentials Settings</Header>}>
              <SpaceBetween size="l">
                <FormField label="Master username" constraintText="1 to 16 alphanumeric characters. The first character must be a letter.">
                  <Input value={f.masterUsername} onChange={({ detail }) => set("masterUsername")(detail.value)} ariaLabel="Master username" />
                </FormField>
                <FormField label="Credentials management">
                  <RadioGroup value={f.credMgmt} onChange={({ detail }) => set("credMgmt")(detail.value)}
                    items={["Managed in AWS Secrets Manager", "Self managed"].map((v) => opt(v))} />
                </FormField>
                {f.credMgmt === "Managed in AWS Secrets Manager" ? (
                  <FormField label="Select the encryption key">
                    <Select selectedOption={SELECT(f.encKey)} onChange={({ detail }) => set("encKey")(detail.selectedOption.value)}
                      options={[opt("aws/secretsmanager (default)")]} ariaLabel="Select the encryption key" />
                  </FormField>
                ) : (
                  <>
                    <Checkbox checked={f.autoGenPw} onChange={({ detail }) => set("autoGenPw")(detail.checked)}>Auto generate password</Checkbox>
                    <FormField label="Master password" constraintText="Minimum constraints: At least 8 printable ASCII characters.">
                      <Input type="password" disabled={f.autoGenPw} value={f.masterPw} onChange={({ detail }) => set("masterPw")(detail.value)} ariaLabel="Master password" />
                    </FormField>
                    <FormField label="Confirm master password">
                      <Input type="password" disabled={f.autoGenPw} value={f.confirmPw} onChange={({ detail }) => set("confirmPw")(detail.value)} ariaLabel="Confirm master password" />
                    </FormField>
                  </>
                )}
              </SpaceBetween>
            </Container>

            <ExpandableSection headerText="Additional credentials settings">
              <FormField label="Database authentication" description="Password authentication is always active for your database engine." />
            </ExpandableSection>

            <Container header={<Header variant="h2">Instance configuration</Header>}>
              <SpaceBetween size="l">
                <FormField label="Type of provisioned configuration">
                  <RadioGroup value={f.provisionedType} onChange={({ detail }) => set("provisionedType")(detail.value)}
                    items={["Memory optimized classes (includes r classes)", "Burstable classes (includes t classes)", "Optimized Reads classes - new"].map((v) => opt(v))} />
                </FormField>
                <FormField label="DB instance class" description={INSTANCE_CLASSES.find((c) => c.value === f.instanceClass)?.label}>
                  <Select selectedOption={{ value: f.instanceClass, label: f.instanceClass }} onChange={({ detail }) => set("instanceClass")(detail.selectedOption.value)}
                    options={INSTANCE_CLASSES} ariaLabel="DB instance class" />
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Storage</Header>}>
              <SpaceBetween size="l">
                <FormField label="Storage type">
                  <Select selectedOption={SELECT(f.storageType)} onChange={({ detail }) => set("storageType")(detail.selectedOption.value)}
                    options={["General Purpose SSD (gp2)", "General Purpose SSD (gp3)", "Provisioned IOPS SSD (io1)", "Provisioned IOPS SSD (io2)", "Magnetic"].map(opt)} ariaLabel="Storage type" />
                </FormField>
                <FormField label="Allocated storage" description="GiB">
                  <Input type="number" value={f.allocatedStorage} onChange={({ detail }) => set("allocatedStorage")(detail.value)} ariaLabel="Allocated storage" />
                </FormField>
                <Checkbox checked={f.storageAutoscale} onChange={({ detail }) => set("storageAutoscale")(detail.checked)}>Enable storage autoscaling</Checkbox>
                {f.storageAutoscale && (
                  <FormField label="Maximum storage threshold">
                    <Input type="number" value={f.maxStorage} onChange={({ detail }) => set("maxStorage")(detail.value)} ariaLabel="Maximum storage threshold" />
                  </FormField>
                )}
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Cluster storage configuration</Header>}>
              <FormField label="Configuration options">
                <RadioGroup value={f.clusterStorageConfig} onChange={({ detail }) => set("clusterStorageConfig")(detail.value)}
                  items={["Aurora I/O-Optimized", "Aurora Standard"].map(opt)} />
              </FormField>
            </Container>

            <Container header={<Header variant="h2">Availability & durability</Header>}>
              <FormField label="Multi-AZ deployment">
                <RadioGroup value={f.multiAzDeployment} onChange={({ detail }) => set("multiAzDeployment")(detail.value)}
                  items={["Create an Aurora Replica or Reader node in a different AZ (recommended for scaled availability)", "Don't create an Aurora Replica"].map(opt)} />
              </FormField>
            </Container>

            <Container header={<Header variant="h2">Connectivity</Header>}>
              <SpaceBetween size="l">
                <FormField label="Compute resource">
                  <RadioGroup value={f.computeResource} onChange={({ detail }) => set("computeResource")(detail.value)}
                    items={["Don't connect to an EC2 compute resource", "Connect to an EC2 compute resource"].map(opt)} />
                </FormField>
                <FormField label="Network type">
                  <RadioGroup value={f.networkType} onChange={({ detail }) => set("networkType")(detail.value)} items={["IPv4", "Dual-stack mode"].map(opt)} />
                </FormField>
                <FormField label="Virtual private cloud (VPC)" description="After a database is created, you can't change its VPC.">
                  <Select selectedOption={SELECT(f.vpc)} onChange={({ detail }) => set("vpc")(detail.selectedOption.value)} options={[opt("Default VPC")]} ariaLabel="Virtual private cloud (VPC)" />
                </FormField>
                <FormField label="DB subnet group">
                  <Select selectedOption={SELECT(f.subnetGroup)} onChange={({ detail }) => set("subnetGroup")(detail.selectedOption.value)} options={[opt("default")]} ariaLabel="DB subnet group" />
                </FormField>
                <FormField label="Public access">
                  <RadioGroup value={f.publicAccess} onChange={({ detail }) => set("publicAccess")(detail.value)} items={["Yes", "No"].map(opt)} />
                </FormField>
                <FormField label="VPC security group (firewall)">
                  <RadioGroup value={f.sgChoice} onChange={({ detail }) => set("sgChoice")(detail.value)} items={["Choose existing", "Create new"].map(opt)} />
                </FormField>
                {f.sgChoice === "Choose existing" ? (
                  <FormField label="Existing VPC security groups">
                    <Select selectedOption={SELECT(f.existingSgs)} onChange={({ detail }) => set("existingSgs")(detail.selectedOption.value)}
                      placeholder="Choose one or more options" options={[opt("default")]} ariaLabel="Existing VPC security groups" />
                  </FormField>
                ) : (
                  <FormField label="New VPC security group name">
                    <Input value={f.newSgName} onChange={({ detail }) => set("newSgName")(detail.value)} ariaLabel="New VPC security group name" />
                  </FormField>
                )}
                <FormField label="Availability Zone">
                  <Select selectedOption={SELECT(f.az)} onChange={({ detail }) => set("az")(detail.selectedOption.value)} options={["No preference", ...AZS].map(opt)} ariaLabel="Availability Zone" />
                </FormField>
                <Checkbox checked={f.rdsProxy} onChange={({ detail }) => set("rdsProxy")(detail.checked)}>RDS Proxy</Checkbox>
                {f.rdsProxy && <NotSimulated feature="RDS Proxy at create time" note="Create the proxy separately from Databases → Proxies." />}
                <FormField label="Certificate authority - optional">
                  <Select selectedOption={SELECT(f.ca)} onChange={({ detail }) => set("ca")(detail.selectedOption.value)}
                    options={[opt("rds-ca-rsa2048-g1"), opt("rds-ca-ecc384-g1")]} ariaLabel="Certificate authority" />
                </FormField>
              </SpaceBetween>
            </Container>

            <ExpandableSection headerText="Additional configuration" defaultExpanded>
              <FormField label="Database port" description="TCP/IP port the database uses for application connections">
                <Input type="number" value={f.port} onChange={({ detail }) => set("port")(detail.value)} ariaLabel="Database port" />
              </FormField>
            </ExpandableSection>

            <Container header={<Header variant="h2">Capacity reservations</Header>}>
              <SpaceBetween size="l">
                <FormField label="Specify capacity reservation - optional">
                  <Select selectedOption={SELECT(f.capRes)} onChange={({ detail }) => set("capRes")(detail.selectedOption.value)} options={[opt("No capacity reservation")]} ariaLabel="Specify capacity reservation" />
                </FormField>
                <FormField label="Specify capacity reservation for Aurora Replica - optional">
                  <Select selectedOption={SELECT(f.capResReplica)} onChange={({ detail }) => set("capResReplica")(detail.selectedOption.value)} options={[opt("No capacity reservation")]} ariaLabel="Specify capacity reservation for Aurora Replica" />
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2" description="You can add up to 50 more tags.">Tags - optional</Header>}>
              <TagEditor tags={f.tags} onChange={({ detail }) => set("tags")(detail.tags)} />
            </Container>

            <Container header={<Header variant="h2">IAM roles - optional</Header>}>
              <SpaceBetween size="l">
                <FormField label="Feature">
                  <Select selectedOption={SELECT(f.iamFeature)} onChange={({ detail }) => set("iamFeature")(detail.selectedOption.value)} placeholder="Choose a feature" options={[opt("s3Import"), opt("s3Export")]} ariaLabel="Feature" />
                </FormField>
                <FormField label="IAM role">
                  <Select selectedOption={SELECT(f.iamRole)} onChange={({ detail }) => set("iamRole")(detail.selectedOption.value)} placeholder="Choose an IAM role" options={[]} ariaLabel="IAM role" />
                </FormField>
                <NotSimulated feature="IAM role association" note="IAM roles for RDS features (S3 import/export) aren't modeled by Vyomi." />
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Babelfish settings</Header>}>
              <Checkbox checked={f.babelfish} onChange={({ detail }) => set("babelfish")(detail.checked)}>Turn on Babelfish</Checkbox>
            </Container>

            <Container header={<Header variant="h2">Monitoring</Header>}>
              <SpaceBetween size="l">
                <FormField label="Database Insights">
                  <RadioGroup value={f.dbInsights} onChange={({ detail }) => set("dbInsights")(detail.value)} items={["Database Insights - Advanced", "Database Insights - Standard"].map(opt)} />
                </FormField>
                <Checkbox checked={f.detailedMetrics} onChange={({ detail }) => set("detailedMetrics")(detail.checked)}>Enable collecting detailed per-query and database counter metrics</Checkbox>
                <FormField label="Retention period">
                  <Select selectedOption={SELECT(f.retentionPeriod)} onChange={({ detail }) => set("retentionPeriod")(detail.selectedOption.value)} options={["7 days (free)", "1 month", "3 months"].map(opt)} ariaLabel="Retention period" />
                </FormField>
                <FormField label="AWS KMS key" description="You can't change the KMS key after you create your database.">
                  <Select selectedOption={SELECT(f.kmsKey)} onChange={({ detail }) => set("kmsKey")(detail.selectedOption.value)} options={[opt("(default) aws/rds")]} ariaLabel="AWS KMS key" />
                </FormField>
                <FormField label="Additional monitoring settings" description="Enhanced Monitoring, CloudWatch Logs and DevOps Guru" />
                <NotSimulated feature="Database Insights metrics" note="Vyomi does not emit RDS CloudWatch metrics; this setting is stored but has nothing to chart." />
              </SpaceBetween>
            </Container>

            <ExpandableSection headerText="Additional configuration">
              <SpaceBetween size="l">
                <FormField label="Initial database name">
                  <Input value={f.initialDbName} onChange={({ detail }) => set("initialDbName")(detail.value)} ariaLabel="Initial database name" />
                </FormField>
                <FormField label="DB parameter group">
                  <Select selectedOption={SELECT(f.paramGroup)} onChange={({ detail }) => set("paramGroup")(detail.selectedOption.value)} options={[opt("default")]} ariaLabel="DB parameter group" />
                </FormField>
                <FormField label="Option group">
                  <Select selectedOption={SELECT(f.optionGroup)} onChange={({ detail }) => set("optionGroup")(detail.selectedOption.value)} placeholder="Choose an option group" options={[]} ariaLabel="Option group" />
                </FormField>
                <Checkbox checked={f.autoBackups} onChange={({ detail }) => set("autoBackups")(detail.checked)}>Enable automated backups</Checkbox>
                <FormField label="Backup retention period">
                  <Select selectedOption={SELECT(f.backupRetention)} onChange={({ detail }) => set("backupRetention")(detail.selectedOption.value)} options={["1 day", "7 days", "14 days", "35 days"].map(opt)} ariaLabel="Backup retention period" />
                </FormField>
                <FormField label="Backup window">
                  <RadioGroup value={f.backupWindow} onChange={({ detail }) => set("backupWindow")(detail.value)} items={["Choose a window", "No preference"].map(opt)} />
                </FormField>
                <Checkbox checked={f.copyTagsToSnapshots} onChange={({ detail }) => set("copyTagsToSnapshots")(detail.checked)}>Copy tags to snapshots</Checkbox>
                <Checkbox checked={f.enableEncryption} onChange={({ detail }) => set("enableEncryption")(detail.checked)}>Enable encryption</Checkbox>
                <Checkbox checked={f.logExports} onChange={({ detail }) => set("logExports")(detail.checked)}>Log exports</Checkbox>
                <Checkbox checked={f.autoMinorUpgrade} onChange={({ detail }) => set("autoMinorUpgrade")(detail.checked)}>Enable auto minor version upgrade</Checkbox>
                <FormField label="Maintenance window">
                  <RadioGroup value={f.maintenanceWindow} onChange={({ detail }) => set("maintenanceWindow")(detail.value)} items={["Choose a window", "No preference"].map(opt)} />
                </FormField>
                <Checkbox checked={f.deletionProtection} onChange={({ detail }) => set("deletionProtection")(detail.checked)}>Enable deletion protection</Checkbox>
              </SpaceBetween>
            </ExpandableSection>

            <Container header={<Header variant="h2">Estimated monthly costs</Header>}>
              <Box variant="awsui-key-label">DB instance</Box>
              <div>Varies — Vyomi does not meter usage-based cost.</div>
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
