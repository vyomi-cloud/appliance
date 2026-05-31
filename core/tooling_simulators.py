from __future__ import annotations

import shlex
from typing import Any


def _result(provider: str, tool: str, command: str, service: str, operation: str, route: str, args: list[str], notes: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "tool": tool,
        "command": command,
        "service": service,
        "operation": operation,
        "route": route,
        "args": args,
        "notes": notes,
    }


def aws_cli_resolve(command: str) -> dict[str, Any]:
    tokens = shlex.split(command or "")
    if not tokens or tokens[0] != "aws":
        return _result("aws", "awscli", command, "", "", "", tokens, "Command must start with `aws`.")
    args = tokens[1:]
    if len(args) >= 2 and args[0] == "s3" and args[1] == "ls":
        return _result("aws", "awscli", command, "s3", "ListBuckets", "GET /", args, "Simulator local S3 root list.")
    if len(args) >= 3 and args[0] == "s3" and args[1] == "mb":
        return _result("aws", "awscli", command, "s3", "CreateBucket", "PUT /{bucket}", args, "Create a bucket in the local simulator.")
    if len(args) >= 3 and args[0] == "s3" and args[1] == "rb":
        return _result("aws", "awscli", command, "s3", "DeleteBucket", "DELETE /{bucket}", args, "Delete a bucket in the local simulator.")
    if len(args) >= 2 and args[0] == "ec2" and args[1] == "describe-instances":
        return _result("aws", "awscli", command, "ec2", "DescribeInstances", "GET /api/ec2/instances", args, "List simulator EC2 instances.")
    if len(args) >= 2 and args[0] == "ec2" and args[1] == "run-instances":
        return _result("aws", "awscli", command, "ec2", "RunInstances", "POST /api/ec2/instances", args, "Launch an EC2 instance locally.")
    if len(args) >= 2 and args[0] == "iam" and args[1] == "list-users":
        return _result("aws", "awscli", command, "iam", "ListUsers", "GET /api/iam/users", args, "List IAM users locally.")
    if len(args) >= 2 and args[0] == "iam" and args[1] == "create-user":
        return _result("aws", "awscli", command, "iam", "CreateUser", "POST /api/iam/users", args, "Create an IAM user locally.")
    if len(args) >= 2 and args[0] == "iam" and args[1] == "list-roles":
        return _result("aws", "awscli", command, "iam", "ListRoles", "GET /api/iam/roles", args, "List IAM roles locally.")
    if len(args) >= 2 and args[0] == "vpc" and args[1] == "describe-vpcs":
        return _result("aws", "awscli", command, "vpc", "DescribeVpcs", "GET /api/vpc/vpcs", args, "List VPCs locally.")
    if len(args) >= 2 and args[0] == "rds" and args[1] == "describe-db-instances":
        return _result("aws", "awscli", command, "rds", "DescribeDBInstances", "GET /api/rds/databases", args, "List RDS databases locally.")
    if len(args) >= 2 and args[0] == "sqs" and args[1] == "list-queues":
        return _result("aws", "awscli", command, "sqs", "ListQueues", "GET /api/sqs/queues", args, "List SQS queues locally.")
    if len(args) >= 2 and args[0] == "sqs" and args[1] == "send-message":
        return _result("aws", "awscli", command, "sqs", "SendMessage", "POST /api/sqs/queues/{queue_name}/messages", args, "Send an SQS message locally.")
    if len(args) >= 2 and args[0] == "dynamodb" and args[1] == "list-tables":
        return _result("aws", "awscli", command, "dynamodb", "ListTables", "GET /api/dynamodb/tables", args, "List DynamoDB tables locally.")
    if len(args) >= 2 and args[0] == "dynamodb" and args[1] == "put-item":
        return _result("aws", "awscli", command, "dynamodb", "PutItem", "POST /api/dynamodb/tables/{table_name}/items", args, "Create a DynamoDB item locally.")
    if len(args) >= 2 and args[0] == "dynamodb" and args[1] == "query":
        return _result("aws", "awscli", command, "dynamodb", "Query", "POST /api/dynamodb/tables/{table_name}/query", args, "Query a DynamoDB table locally.")
    if len(args) >= 2 and args[0] == "lambda" and args[1] == "list-functions":
        return _result("aws", "awscli", command, "lambda", "ListFunctions", "GET /api/lambda/functions", args, "List simulator Lambda functions.")
    if len(args) >= 2 and args[0] == "lambda" and args[1] == "invoke":
        return _result("aws", "awscli", command, "lambda", "Invoke", "POST /api/lambda/functions/{function_name}/invoke", args, "Invoke a Lambda function locally.")
    if len(args) >= 2 and args[0] == "apigateway" and args[1] in {"get-rest-apis", "get-apis"}:
        return _result("aws", "awscli", command, "apigateway", "GetRestApis", "GET /api/apigateway/apis", args, "List API Gateway APIs locally.")
    if len(args) >= 2 and args[0] == "apigateway" and args[1] in {"create-rest-api", "create-api"}:
        return _result("aws", "awscli", command, "apigateway", "CreateRestApi", "POST /api/apigateway/apis", args, "Create an API Gateway API locally.")
    return _result("aws", "awscli", command, "", "", "", args, "No translation rule exists yet.")


def gcp_gcloud_resolve(command: str) -> dict[str, Any]:
    tokens = shlex.split(command or "")
    if not tokens or tokens[0] != "gcloud":
        return _result("gcp", "gcloud", command, "", "", "", tokens, "Command must start with `gcloud`.")
    args = tokens[1:]
    if len(args) >= 3 and args[0] == "compute" and args[1] == "instances" and args[2] == "list":
        return _result("gcp", "gcloud", command, "compute", "instances.list", "GET /compute/v1/projects/{project}/zones/{zone}/instances", args, "List Compute Engine instances in the local simulator.")
    if len(args) >= 3 and args[0] == "compute" and args[1] == "instances" and args[2] == "create":
        return _result("gcp", "gcloud", command, "compute", "instances.insert", "POST /compute/v1/projects/{project}/zones/{zone}/instances", args, "Create a Compute Engine instance locally.")
    if len(args) >= 3 and args[0] == "compute" and args[1] == "instances" and args[2] == "describe":
        return _result("gcp", "gcloud", command, "compute", "instances.get", "GET /compute/v1/projects/{project}/zones/{zone}/instances/{instance}", args, "Describe a Compute Engine instance locally.")
    if len(args) >= 3 and args[0] == "compute" and args[1] == "instances" and args[2] == "start":
        return _result("gcp", "gcloud", command, "compute", "instances.start", "POST /compute/v1/projects/{project}/zones/{zone}/instances/{instance}/start", args, "Start a Compute Engine instance locally.")
    if len(args) >= 3 and args[0] == "compute" and args[1] == "instances" and args[2] == "stop":
        return _result("gcp", "gcloud", command, "compute", "instances.stop", "POST /compute/v1/projects/{project}/zones/{zone}/instances/{instance}/stop", args, "Stop a Compute Engine instance locally.")
    if len(args) >= 3 and args[0] == "compute" and args[1] == "instances" and args[2] == "delete":
        return _result("gcp", "gcloud", command, "compute", "instances.delete", "DELETE /compute/v1/projects/{project}/zones/{zone}/instances/{instance}", args, "Delete a Compute Engine instance locally.")
    if len(args) >= 3 and args[0] == "storage" and args[1] == "buckets" and args[2] == "list":
        return _result("gcp", "gcloud", command, "storage", "buckets.list", "GET /storage/v1/b", args, "List Cloud Storage buckets locally.")
    if len(args) >= 3 and args[0] == "storage" and args[1] == "buckets" and args[2] == "create":
        return _result("gcp", "gcloud", command, "storage", "buckets.insert", "POST /storage/v1/b", args, "Create a Cloud Storage bucket locally.")
    if len(args) >= 3 and args[0] == "storage" and args[1] == "buckets" and args[2] == "delete":
        return _result("gcp", "gcloud", command, "storage", "buckets.delete", "DELETE /storage/v1/b/{bucket}", args, "Delete a Cloud Storage bucket locally.")
    if len(args) >= 3 and args[0] == "sql" and args[1] == "instances" and args[2] == "list":
        return _result("gcp", "gcloud", command, "sql", "instances.list", "GET /sql/v1beta4/projects/{project}/instances", args, "List Cloud SQL instances locally.")
    if len(args) >= 3 and args[0] == "sql" and args[1] == "instances" and args[2] == "create":
        return _result("gcp", "gcloud", command, "sql", "instances.insert", "POST /sql/v1beta4/projects/{project}/instances", args, "Create a Cloud SQL instance locally.")
    if len(args) >= 3 and args[0] == "sql" and args[1] == "instances" and args[2] == "delete":
        return _result("gcp", "gcloud", command, "sql", "instances.delete", "DELETE /sql/v1beta4/projects/{project}/instances/{instance}", args, "Delete a Cloud SQL instance locally.")
    if len(args) >= 3 and args[0] == "pubsub" and args[1] == "topics" and args[2] == "list":
        return _result("gcp", "gcloud", command, "pubsub", "topics.list", "GET /v1/projects/{project}/topics", args, "List Pub/Sub topics locally.")
    if len(args) >= 3 and args[0] == "pubsub" and args[1] == "topics" and args[2] == "create":
        return _result("gcp", "gcloud", command, "pubsub", "topics.create", "POST /v1/projects/{project}/topics", args, "Create a Pub/Sub topic locally.")
    if len(args) >= 3 and args[0] == "pubsub" and args[1] == "topics" and args[2] == "delete":
        return _result("gcp", "gcloud", command, "pubsub", "topics.delete", "DELETE /v1/projects/{project}/topics/{topic}", args, "Delete a Pub/Sub topic locally.")
    if len(args) >= 3 and args[0] == "compute" and args[1] == "networks" and args[2] == "list":
        return _result("gcp", "gcloud", command, "vpc", "networks.list", "GET /compute/v1/projects/{project}/global/networks", args, "List VPC networks locally.")
    if len(args) >= 3 and args[0] == "compute" and args[1] == "firewall-rules" and args[2] == "list":
        return _result("gcp", "gcloud", command, "vpc", "firewalls.list", "GET /compute/v1/projects/{project}/global/firewalls", args, "List firewall rules locally.")
    if len(args) >= 3 and args[0] == "iam" and args[1] == "service-accounts" and args[2] == "list":
        return _result("gcp", "gcloud", command, "iam", "serviceAccounts.list", "GET /v1/projects/{project}/serviceAccounts", args, "List service accounts locally.")
    return _result("gcp", "gcloud", command, "", "", "", args, "No translation rule exists yet.")


def gcp_gcutil_resolve(command: str) -> dict[str, Any]:
    tokens = shlex.split(command or "")
    if not tokens or tokens[0] != "gcutil":
        return _result("gcp", "gcutil", command, "", "", "", tokens, "Command must start with `gcutil`.")
    args = tokens[1:]
    if args and args[0] == "listinstances":
        return _result("gcp", "gcutil", command, "compute", "instances.list", "GET /compute/v1/projects/{project}/zones/{zone}/instances", args, "Legacy gcutil instance listing.")
    if args and args[0] == "addinstance":
        return _result("gcp", "gcutil", command, "compute", "instances.insert", "POST /compute/v1/projects/{project}/zones/{zone}/instances", args, "Legacy gcutil instance creation.")
    if args and args[0] == "getinstance":
        return _result("gcp", "gcutil", command, "compute", "instances.get", "GET /compute/v1/projects/{project}/zones/{zone}/instances/{instance}", args, "Legacy gcutil instance description.")
    if args and args[0] == "startinstance":
        return _result("gcp", "gcutil", command, "compute", "instances.start", "POST /compute/v1/projects/{project}/zones/{zone}/instances/{instance}/start", args, "Legacy gcutil instance start.")
    if args and args[0] == "stopinstance":
        return _result("gcp", "gcutil", command, "compute", "instances.stop", "POST /compute/v1/projects/{project}/zones/{zone}/instances/{instance}/stop", args, "Legacy gcutil instance stop.")
    if args and args[0] == "delinstance":
        return _result("gcp", "gcutil", command, "compute", "instances.delete", "DELETE /compute/v1/projects/{project}/zones/{zone}/instances/{instance}", args, "Legacy gcutil instance deletion.")
    if args and args[0] == "ls" and "bucket" in args:
        return _result("gcp", "gcutil", command, "storage", "buckets.list", "GET /storage/v1/b", args, "Legacy gcutil bucket listing.")
    if args and args[0] == "addbucket":
        return _result("gcp", "gcutil", command, "storage", "buckets.insert", "POST /storage/v1/b", args, "Legacy gcutil bucket creation.")
    if args and args[0] == "delbucket":
        return _result("gcp", "gcutil", command, "storage", "buckets.delete", "DELETE /storage/v1/b/{bucket}", args, "Legacy gcutil bucket deletion.")
    if args and args[0] == "ls" and "topic" in args:
        return _result("gcp", "gcutil", command, "pubsub", "topics.list", "GET /v1/projects/{project}/topics", args, "Legacy gcutil topic listing.")
    if args and args[0] == "addtopic":
        return _result("gcp", "gcutil", command, "pubsub", "topics.create", "POST /v1/projects/{project}/topics", args, "Legacy gcutil topic creation.")
    if args and args[0] == "deltopic":
        return _result("gcp", "gcutil", command, "pubsub", "topics.delete", "DELETE /v1/projects/{project}/topics/{topic}", args, "Legacy gcutil topic deletion.")
    return _result("gcp", "gcutil", command, "", "", "", args, "No translation rule exists yet.")


def sdk_snippet(provider: str, language: str) -> dict[str, Any]:
    provider = provider.lower()
    language = language.lower()
    endpoint = "http://127.0.0.1:9000"
    if provider == "aws" and language == "java":
        return {
            "provider": "aws",
            "language": "java",
            "endpoint": endpoint,
            "snippet": """S3Client client = S3Client.builder()
    .endpointOverride(URI.create("http://127.0.0.1:9000"))
    .region(Region.US_EAST_1)
    .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
    .build();""",
        }
    if provider == "aws" and language == "go":
        return {
            "provider": "aws",
            "language": "go",
            "endpoint": endpoint,
            "snippet": """cfg, _ := config.LoadDefaultConfig(context.TODO(),
    config.WithRegion("us-east-1"),
    config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test")),
)
client := s3.NewFromConfig(cfg, func(o *s3.Options) {
    o.BaseEndpoint = aws.String("http://127.0.0.1:9000")
})""",
        }
    if provider == "gcp" and language == "java":
        return {
            "provider": "gcp",
            "language": "java",
            "endpoint": endpoint,
            "snippet": """Storage storage = StorageOptions.newBuilder()
    .setHost("http://127.0.0.1:9000")
    .setProjectId("cloudlearn")
    .build()
    .getService();""",
        }
    if provider == "gcp" and language == "go":
        return {
            "provider": "gcp",
            "language": "go",
            "endpoint": endpoint,
            "snippet": """client, _ := storage.NewClient(ctx,
    option.WithEndpoint("http://127.0.0.1:9000"),
    option.WithoutAuthentication(),
)""",
        }
    # Azure SDK snippets — added 2026-06-01 for pack-architecture parity.
    if provider == "azure" and language == "java":
        return {
            "provider": "azure",
            "language": "java",
            "endpoint": endpoint,
            "snippet": """AzureProfile profile = new AzureProfile(
    "tenant-sim", "sub-001", AzureEnvironment.AZURE);
HttpPipeline pipeline = HttpPipelineProvider.buildHttpPipeline(
    new AzureCliCredentialBuilder().build(),
    new AzureProfile(AzureEnvironment.AZURE));
// Point all ARM clients at the simulator:
ComputeManager mgr = ComputeManager.authenticate(pipeline, profile);
mgr.virtualMachines().list();""",
        }
    if provider == "azure" and language == "go":
        return {
            "provider": "azure",
            "language": "go",
            "endpoint": endpoint,
            "snippet": """cred, _ := azidentity.NewDefaultAzureCredential(nil)
opts := &arm.ClientOptions{
    ClientOptions: azcore.ClientOptions{
        Cloud: cloud.Configuration{
            Services: map[cloud.ServiceName]cloud.ServiceConfiguration{
                cloud.ResourceManager: {Endpoint: "http://127.0.0.1:9000",
                                        Audience: "http://127.0.0.1:9000"},
            },
        },
    },
}
client, _ := armcompute.NewVirtualMachinesClient("sub-001", cred, opts)""",
        }
    return {"provider": provider, "language": language, "endpoint": endpoint, "snippet": "", "status": "planned"}


def az_cli_resolve(command: str) -> dict[str, Any]:
    """Map an ``az <group> <subgroup> <verb>`` command to an ARM operation +
    route. Mirrors aws_cli_resolve / gcp_gcloud_resolve. Returns the same
    _result shape so the SPA can render it uniformly.
    """
    tokens = shlex.split(command or "")
    if not tokens or tokens[0] != "az":
        return _result("azure", "az", command, "", "", "", tokens, "Command must start with `az`.")
    args = tokens[1:]
    api = "api-version=2024-03-01"
    # vm list / show / create / delete / start / deallocate / restart
    if len(args) >= 2 and args[0] == "vm":
        verb = args[1]
        verb_map = {
            "list": ("VirtualMachines_ListAll",
                     "GET /subscriptions/{sub}/providers/Microsoft.Compute/virtualMachines"),
            "show": ("VirtualMachines_Get",
                     "GET /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{name}"),
            "create": ("VirtualMachines_CreateOrUpdate",
                       "PUT /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{name}"),
            "delete": ("VirtualMachines_Delete",
                       "DELETE /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{name}"),
            "start": ("VirtualMachines_Start",
                      "POST .../Microsoft.Compute/virtualMachines/{name}/start"),
            "deallocate": ("VirtualMachines_Deallocate",
                           "POST .../Microsoft.Compute/virtualMachines/{name}/deallocate"),
            "restart": ("VirtualMachines_Restart",
                        "POST .../Microsoft.Compute/virtualMachines/{name}/restart"),
        }
        if verb in verb_map:
            op, route = verb_map[verb]
            return _result("azure", "az", command, "Microsoft.Compute", op, f"{route}?{api}", args,
                           "Azure CLI vm command → ARM route. Real az CLI works when ARM endpoint points at simulator.")
    # storage account list / show / create / delete
    if len(args) >= 3 and args[0] == "storage" and args[1] == "account":
        verb = args[2]
        verb_map = {
            "list": ("StorageAccounts_List",
                     "GET /subscriptions/{sub}/providers/Microsoft.Storage/storageAccounts"),
            "show": ("StorageAccounts_GetProperties",
                     "GET .../Microsoft.Storage/storageAccounts/{name}"),
            "create": ("StorageAccounts_Create",
                       "PUT .../Microsoft.Storage/storageAccounts/{name}"),
            "delete": ("StorageAccounts_Delete",
                       "DELETE .../Microsoft.Storage/storageAccounts/{name}"),
        }
        if verb in verb_map:
            op, route = verb_map[verb]
            return _result("azure", "az", command, "Microsoft.Storage", op, f"{route}?{api}", args,
                           "Real Blob bytes back this surface via fake-gcs-server bridge.")
    # sql server list / db create
    if len(args) >= 2 and args[0] == "sql":
        if args[1] == "server" and len(args) >= 3:
            return _result("azure", "az", command, "Microsoft.Sql",
                           f"Servers_{args[2].title()}", "/subscriptions/{sub}/.../Microsoft.Sql/servers", args, "")
        if args[1] == "db" and len(args) >= 3:
            return _result("azure", "az", command, "Microsoft.Sql",
                           f"Databases_{args[2].title()}", ".../Microsoft.Sql/servers/{srv}/databases", args,
                           "Backed by real Postgres via gcp_sql_engine.")
    # generic group/verb fallback so any az command is reflected back.
    if len(args) >= 2:
        return _result("azure", "az", command, args[0], args[1], "azure-arm", args,
                       f"Generic az {args[0]} {args[1]} dispatch. Implement explicitly for stronger mapping.")
    return _result("azure", "az", command, args[0] if args else "", "", "", args,
                   "Subcommand required (e.g. `az vm list`).")
