/* Create database by restoring from S3: RestoreDBInstanceFromS3 against the simulator's own S3 (core/rds_restore_core.py). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const CLASSES = ["db.t3.micro", "db.t3.small", "db.t3.medium", "db.m5.large", "db.r5.large"].map((v) => ({ value: v, label: v }));

export default function RestoreFromS3() {
  const notify = useNotify();
  const [f, setF] = useState({ id: "", cls: CLASSES[0], bucket: "", prefix: "", srcVersion: "8.0.36", role: "", user: "admin", pass: "" });
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => ({ detail }) => setF((p) => ({ ...p, [k]: detail.value ?? detail.selectedOption }));
  const missing = (v) => touched && !String(v || "").trim() ? "This field is required." : undefined;
  const submit = async () => {
    setTouched(true);
    if (!f.id.trim() || !f.bucket.trim() || !f.role.trim() || !f.user.trim() || !f.pass.trim()) return;
    setBusy(true); setError(null);
    try {
      await api.restoreDBInstanceFromS3({ DBInstanceIdentifier: f.id.trim(), DBInstanceClass: f.cls.value, Engine: "mysql", SourceEngine: "mysql",
        SourceEngineVersion: f.srcVersion.trim(), S3BucketName: f.bucket.trim(), S3Prefix: f.prefix.trim(), S3IngestionRoleArn: f.role.trim(),
        MasterUsername: f.user.trim(), MasterUserPassword: f.pass });
      notify.success(`Restoring the ${f.id.trim()} database from S3.`);
      navigate("rds", "databases");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <ContentLayout header={<Header variant="h1">Create database by restoring from S3</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form errorText={error && <ErrorAlert error={error} />} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href="#/rds/databases" onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Restore database</Button>
          </SpaceBetween>}>
          <SpaceBetween size="l">
            <CapabilityContainer id="rds.restore-from-s3" title="Source backup" description="Backup files in the simulator's own S3: .sql / .sql.gz dumps (including mysqldump output), or an RDS snapshot export (Parquet).">
              <SpaceBetween size="l">
                <FormField label="S3 bucket" errorText={missing(f.bucket)}><Input value={f.bucket} onChange={set("bucket")} ariaLabel="S3 bucket" placeholder="my-backup-bucket" /></FormField>
                <FormField label="S3 prefix - optional" description="Restores every backup file under this prefix."><Input value={f.prefix} onChange={set("prefix")} ariaLabel="S3 prefix" placeholder="backups/mysql/" /></FormField>
                <FormField label="Source engine"><Input value="MySQL" readOnly ariaLabel="Source engine" /></FormField>
                <FormField label="Source engine version"><Input value={f.srcVersion} onChange={set("srcVersion")} ariaLabel="Source engine version" /></FormField>
                <FormField label="IAM role" description="Role RDS assumes to read the bucket (ARN)." errorText={missing(f.role)}>
                  <Input value={f.role} onChange={set("role")} ariaLabel="IAM role" placeholder="arn:aws:iam::123456789012:role/rds-s3-ingest" /></FormField>
              </SpaceBetween>
            </CapabilityContainer>
            <CapabilityContainer noBadge id="rds.restore-from-s3" title="Settings">
              <SpaceBetween size="l">
                <FormField label="DB instance identifier" errorText={missing(f.id)}><Input value={f.id} onChange={set("id")} ariaLabel="DB instance identifier" /></FormField>
                <FormField label="DB instance class"><Select selectedOption={f.cls} options={CLASSES} onChange={set("cls")} ariaLabel="DB instance class" /></FormField>
                <FormField label="Master username" errorText={missing(f.user)}><Input value={f.user} onChange={set("user")} ariaLabel="Master username" /></FormField>
                <FormField label="Master password" errorText={missing(f.pass)}><Input type="password" value={f.pass} onChange={set("pass")} ariaLabel="Master password" /></FormField>
              </SpaceBetween>
            </CapabilityContainer>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
