/* Entry point from a data-service page into the AWS Backup console. */
import Alert from "@cloudscape-design/components/alert";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import { follow } from "../../common/router.js";

export default function BackupLink({ service, resource }) {
  return (
    <Alert type="info" header="Centralized backup with AWS Backup"
      action={<Button href="#/backup/plans" onFollow={follow}>Backup plans</Button>}>
      Protect {service} {resource} on a schedule with an AWS Backup plan, then review them under{" "}
      <Link href="#/backup/protected-resources" onFollow={follow}>Protected resources</Link> and recovery points in a <Link href="#/backup/vaults" onFollow={follow}>vault</Link>.
    </Alert>
  );
}
