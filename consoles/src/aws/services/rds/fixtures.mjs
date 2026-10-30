/* UI-conformance fixtures for RDS (native Query-protocol form-encoded POST). See s3/fixtures.mjs. */
const Q = (action, params = {}) => ({
  svc: "rds",
  headers: { "content-type": "application/x-www-form-urlencoded; charset=utf-8" },
  body: new URLSearchParams({ Action: action, ...params }).toString(),
});

export default {
  "live-database": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateDBInstance", { DBInstanceIdentifier: uniq, Engine: "postgres", MasterUsername: "admin" }));
    return uniq;
  },
  // database-detail's title is the fixed spec placeholder "{resource-name}" (resolved via
  // spec-map `vars`, not per-run), so it needs a STABLE instance id; liveness for that same
  // page is proven separately via a uniquely-tagged value shown in its Tags tab.
  "rds-database": async (wire) => {
    await wire("POST", "/", Q("CreateDBInstance", { DBInstanceIdentifier: "uic-database", Engine: "postgres", MasterUsername: "admin" })).catch(() => {});
  },
  "live-database-tag": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateDBInstance", { DBInstanceIdentifier: "uic-database", Engine: "postgres", MasterUsername: "admin" })).catch(() => {});
    await wire("POST", "/", Q("AddTagsToResource", {
      ResourceName: "arn:aws:rds:us-east-1:123456789012:db:uic-database",
      "Tags.member.1.Key": "live", "Tags.member.1.Value": uniq,
    }));
    return uniq;
  },
  "live-snapshot": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateDBInstance", { DBInstanceIdentifier: `${uniq}db`, Engine: "postgres" })).catch(() => {});
    await wire("POST", "/", Q("CreateDBSnapshot", { DBInstanceIdentifier: `${uniq}db`, DBSnapshotIdentifier: uniq }));
    return uniq;
  },
  "live-subnet-group": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateDBSubnetGroup", { DBSubnetGroupName: uniq, DBSubnetGroupDescription: "v4 live", "SubnetIds.member.1": "subnet-a" }));
    return uniq;
  },
  "live-parameter-group": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateDBParameterGroup", { DBParameterGroupName: uniq, DBParameterGroupFamily: "postgres16", Description: "v4 live" }));
    return uniq;
  },
  // parameter-group-detail's title is also the fixed "{resource-name}" placeholder — same
  // fixed-id + separately-proven-live pattern as the database detail page above.
  "rds-parameter-group": async (wire) => {
    await wire("POST", "/", Q("CreateDBParameterGroup", { DBParameterGroupName: "uic-paramgroup", DBParameterGroupFamily: "postgres16", Description: "v4 fixed" })).catch(() => {});
  },
  "live-parameter-group-value": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateDBParameterGroup", { DBParameterGroupName: "uic-paramgroup", DBParameterGroupFamily: "postgres16", Description: "v4 fixed" })).catch(() => {});
    await wire("POST", "/", Q("ModifyDBParameterGroup", {
      DBParameterGroupName: "uic-paramgroup",
      "Parameters.member.1.ParameterName": "max_connections", "Parameters.member.1.ParameterValue": uniq,
    }));
    return uniq;
  },
  "live-proxy": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateDBProxy", { DBProxyName: uniq, EngineFamily: "POSTGRESQL" }));
    return uniq;
  },
  "live-option-group": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateOptionGroup", { OptionGroupName: uniq, OptionGroupDescription: "v4 live", EngineName: "mysql", MajorEngineVersion: "8.0" }));
    return uniq;
  },
  "live-event-subscription": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateEventSubscription", { SubscriptionName: uniq, SnsTopicArn: "arn:aws:sns:us-east-1:123456789012:t", SourceType: "db-instance" }));
    return uniq;
  },
  "live-event": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateDBInstance", { DBInstanceIdentifier: uniq, Engine: "postgres" }));
    return uniq;
  },
  "live-automated-backup": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateDBInstance", { DBInstanceIdentifier: uniq, Engine: "postgres" }));
    return uniq;
  },
  // Not Multi-AZ (the default) is a real recommendation condition — see
  // core/rds_core.py _recommendations_for; the resource identifier column
  // shows the instance ARN, which carries this unique id.
  "live-recommendation": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateDBInstance", { DBInstanceIdentifier: uniq, Engine: "postgres" }));
    return uniq;
  },
  // Any CA other than the current default is flagged for a certificate update.
  "live-certificate-update": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateDBInstance", { DBInstanceIdentifier: uniq, Engine: "postgres", CACertificateIdentifier: "rds-ca-2019" }));
    return uniq;
  },
  "live-reserved-instance": async (wire, uniq) => {
    await wire("POST", "/", Q("PurchaseReservedDBInstancesOffering", { ReservedDBInstanceId: uniq }));
    return uniq;
  },
  "live-export-task": async (wire, uniq) => {
    await wire("POST", "/", Q("StartExportTask", {
      ExportTaskIdentifier: uniq,
      SourceArn: `arn:aws:rds:us-east-1:123456789012:snapshot:${uniq}-snap`,
      S3BucketName: `${uniq}-bucket`,
      IamRoleArn: "arn:aws:iam::123456789012:role/rds-s3-export",
    }));
    return uniq;
  },
  "live-integration": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateIntegration", {
      IntegrationName: uniq,
      SourceArn: `arn:aws:rds:us-east-1:123456789012:db:${uniq}-source`,
      TargetArn: "arn:aws:redshift-serverless:us-east-1:123456789012:namespace/v4-smoke",
    }));
    return uniq;
  },
  "live-custom-engine-version": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateCustomDBEngineVersion", { Engine: "custom-oracle-ee", EngineVersion: uniq }));
    return uniq;
  },
};
