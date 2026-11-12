/* Reference data (engine/version/instance-class catalogues). These are enumeration
 * lists the native console pre-populates from AWS's own catalogue service — not user
 * resource state — so, like KMS's KeySpec options, they're shipped as static options
 * rather than round-tripped through a native call. */

export const ENGINES = [
  "Aurora (MySQL Compatible)", "Aurora (PostgreSQL Compatible)", "MySQL", "PostgreSQL",
  "MariaDB", "Oracle", "Microsoft SQL Server", "IBM Db2",
];

export const ENGINE_WIRE = {
  "Aurora (MySQL Compatible)": "aurora-mysql",
  "Aurora (PostgreSQL Compatible)": "aurora-postgresql",
  "MySQL": "mysql",
  "PostgreSQL": "postgres",
  "MariaDB": "mariadb",
  "Oracle": "oracle-ee",
  "Microsoft SQL Server": "sqlserver-ee",
  "IBM Db2": "db2-ee",
};

export const ENGINE_VERSIONS = {
  "aurora-mysql": ["8.0.mysql_aurora.3.07.1", "8.0.mysql_aurora.3.05.2"],
  "aurora-postgresql": ["16.4", "15.8", "14.12"],
  "mysql": ["8.0.37", "8.0.35", "5.7.44"],
  "postgres": ["16.4", "15.8", "14.12", "13.15"],
  "mariadb": ["10.11.8", "10.6.18"],
  "oracle-ee": ["19.0.0.0.ru-2024-07.rur-2024-07.r1"],
  "sqlserver-ee": ["16.00.4120.2.v1"],
  "db2-ee": ["11.5.9.0"],
};

export const isAurora = (engineLabel) => engineLabel.startsWith("Aurora");

export const INSTANCE_CLASSES = [
  { value: "db.r7g.large", label: "db.r7g.large — 2 vCPUs, 16 GiB RAM" },
  { value: "db.r6g.large", label: "db.r6g.large — 2 vCPUs, 16 GiB RAM" },
  { value: "db.t4g.medium", label: "db.t4g.medium — 2 vCPUs, 4 GiB RAM" },
  { value: "db.t3.micro", label: "db.t3.micro — 2 vCPUs, 1 GiB RAM" },
  { value: "db.m6g.large", label: "db.m6g.large — 2 vCPUs, 8 GiB RAM" },
];

export const AZS = ["us-east-1a", "us-east-1b", "us-east-1c"];
