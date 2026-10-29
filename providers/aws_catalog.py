"""AWS catalog for the standalone /console/aws SPA.

Defines the metadata each AWS service needs for the catalog-driven console
renderer to fetch / list / create / update / delete + drive sub-blades:

    - service:        AWS service name (used as `aws.<service>.*` for telemetry)
    - namespace:      "AWS/<Service>" — display prefix
    - collection_path: GET → list resources, POST → create
    - resource_path:  GET/PATCH/DELETE — single resource. {name} placeholder.
    - name_field:     attr on the response that holds the canonical name/ID
    - api_paths:      per-action method+URL templates (start/stop/reboot/etc.)
    - children:       sub-collections nested under a parent (e.g. RDS snapshots)
    - columns:        grid columns
    - createFields:   flat backward-compat fields
    - wizard:         multi-step wizard from core/aws_wizards.py
    - subBlades:      detail-blade sub-nav from core/aws_subblades.py

The shape mirrors providers/azure_services.py:RESOURCE_CATALOG so the same
``catalog_for_console`` pattern works.
"""
from __future__ import annotations


# ---------- AWS service catalog -------------------------------------------

# --- rail_items reference ---------------------------------------------------
# Each service may declare `rail_items` (an ordered list) that the AWS console
# renders as its left service navigation. Each item is one of:
#   {key, label, icon, type:"primary"}                       # the service's main list
#   {key, label, icon, type:"child",  child_key:"<x>"}       # wired child via childSpec
#   {key, label, icon, type:"link",   link_service:"<svc>",
#                                     link_child:"<x>"}      # routes to another svc's child
#   {key, label, icon, type:"stub"}                          # "Coming soon" placeholder
# A bare entry {group:"<heading>"} renders as a section header.
# rail_items is preferred over the legacy `children` list when both exist.

RESOURCE_CATALOG_AWS = [
    {
        "key": "ec2", "label": "EC2", "icon": "computer",
        "namespace": "AWS/EC2", "service": "ec2",
        "collection_path": "/api/ec2/instances",
        "resource_path":   "/api/ec2/instances/{name}",
        "name_field":      "instance_id",
        "create_method":   "POST",
        "rail_items": [
            {"key": "events",          "label": "Events",            "icon": "event",          "type": "stub"},
            {"key": "tag-editor",      "label": "Tag Editor",        "icon": "sell",           "type": "stub"},
            {"group": "Instances"},
            {"key": "instances",       "label": "Instances",         "icon": "computer",       "type": "primary"},
            {"key": "instance-types",  "label": "Instance Types",    "icon": "tune",           "type": "stub"},
            {"key": "launch-templates","label": "Launch Templates",  "icon": "rocket_launch",  "type": "stub"},
            {"key": "spot-requests",   "label": "Spot Requests",     "icon": "bolt",           "type": "stub"},
            {"group": "Images"},
            {"key": "amis",            "label": "AMIs",              "icon": "image",
                "type": "child", "child_key": "amis"},
            {"key": "ami-catalog",     "label": "AMI Catalog",       "icon": "view_list",      "type": "stub"},
            {"group": "Elastic Block Store"},
            {"key": "volumes",         "label": "Volumes",           "icon": "storage",        "type": "stub"},
            {"key": "snapshots",       "label": "Snapshots",         "icon": "photo_camera",   "type": "stub"},
            {"group": "Network & Security"},
            {"key": "sgs",             "label": "Security Groups",   "icon": "shield",
                "type": "link", "link_service": "vpc", "link_child": "security-groups"},
            {"key": "elastic-ips",     "label": "Elastic IPs",       "icon": "public",         "type": "stub"},
            {"key": "key-pairs",       "label": "Key Pairs",         "icon": "vpn_key",        "type": "stub"},
            {"key": "network-ifs",     "label": "Network Interfaces","icon": "lan",            "type": "stub"},
            {"group": "Load Balancing"},
            {"key": "load-balancers",  "label": "Load Balancers",    "icon": "balance",        "type": "stub"},
            {"key": "target-groups",   "label": "Target Groups",     "icon": "ads_click",      "type": "stub"},
            {"group": "Auto Scaling"},
            {"key": "asg",             "label": "Auto Scaling Groups","icon": "auto_awesome",  "type": "stub"},
        ],
        "api_paths": {
            "start":     {"method": "POST", "path": "/api/ec2/instances/{name}/start"},
            "stop":      {"method": "POST", "path": "/api/ec2/instances/{name}/stop"},
            "reboot":    {"method": "POST", "path": "/api/ec2/instances/{name}/reboot"},
            "terminate": {"method": "POST", "path": "/api/ec2/instances/{name}/terminate"},
            "amis":      {"method": "GET",  "path": "/api/ec2/amis"},
        },
        "columns": [
            ["instance_id",     "Instance ID"],
            ["name",            "Name"],
            ["instance_type",   "Instance type"],
            ["state",           "State"],
            ["public_ip",       "Public IPv4"],
            ["private_ip",      "Private IPv4"],
        ],
        "createFields": [
            {"name": "name", "label": "Name", "default": "my-ec2"},
            {"name": "instance_type", "label": "Instance type", "default": "t3.micro"},
            {"name": "image_id", "label": "AMI", "default": "ami-amzn2023-x86_64"},
        ],
        "endpoints": {},
    },
    {
        "key": "s3", "label": "S3", "icon": "storage",
        "namespace": "AWS/S3", "service": "s3",
        "collection_path": "/api/s3/buckets",
        "resource_path":   "/api/s3/buckets/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        # S3 wire protocol nests the bucket name in the path for create
        # (POST /api/s3/buckets/{name}) — not the collection. Override
        # so the console renderer doesn't hit /api/s3/buckets which the
        # S3 catch-all eats as NoSuchBucket.
        "create_path":     "/api/s3/buckets/{name}",
        "rail_items": [
            {"key": "buckets",         "label": "General purpose buckets","icon": "storage",   "type": "primary"},
            {"key": "directory",       "label": "Directory buckets",   "icon": "folder_special","type": "stub"},
            {"key": "table-buckets",   "label": "Table buckets",       "icon": "table_chart",  "type": "stub"},
            {"key": "access-points",   "label": "Access Points",       "icon": "hub",          "type": "stub"},
            {"key": "mrap",            "label": "Multi-Region Access Points","icon": "public", "type": "stub"},
            {"key": "batch-ops",       "label": "Batch Operations",    "icon": "playlist_play","type": "stub"},
            {"key": "storage-lens",    "label": "Storage Lens",        "icon": "monitoring",   "type": "stub"},
            {"key": "block-public",    "label": "Block Public Access",  "icon": "shield",      "type": "stub"},
        ],
        "api_paths": {
            "versioning":     {"method": "PUT", "path": "/api/s3/buckets/{name}/versioning"},
            "notifications":  {"method": "PUT", "path": "/api/s3/buckets/{name}/notification"},
            "objects":        {"method": "GET", "path": "/api/s3/buckets/{name}/objects"},
            "uploadObject":   {"method": "POST","path": "/api/s3/buckets/{name}/objects"},
            "deleteObject":   {"method": "DELETE","path": "/api/s3/buckets/{name}/objects/{key}"},
        },
        "children": [
            {"type": "objects", "label": "Objects", "icon": "folder"},
        ],
        "columns": [
            ["name",          "Name"],
            ["creation_date", "Creation date"],
            ["region",        "Region"],
            ["versioning",    "Versioning"],
        ],
        "createFields": [
            {"name": "name", "label": "Bucket name", "default": "my-bucket"},
            {"name": "versioning_enabled", "label": "Versioning", "default": False},
        ],
        "endpoints": {},
    },
    {
        # IAM is a composite — the console exposes 4 sub-collections under one
        # service entry. The frontend handles the per-sub-blade fetch using
        # the api_paths.
        "key": "iam", "label": "IAM", "icon": "admin_panel_settings",
        "namespace": "AWS/IAM", "service": "iam",
        # The primary "list" returns users; sub-blades take you to the others.
        "collection_path": "/api/iam/users",
        "resource_path":   "/api/iam/users/{name}",
        "name_field":      "user_name",
        "create_method":   "POST",
        "rail_items": [
            {"key": "dashboard",       "label": "Dashboard",            "icon": "dashboard",    "type": "stub"},
            {"group": "Access management"},
            {"key": "users",           "label": "Users",                "icon": "person",       "type": "primary"},
            {"key": "groups",          "label": "User groups",          "icon": "group",
                "type": "child", "child_key": "iam-groups"},
            {"key": "roles",           "label": "Roles",                "icon": "badge",
                "type": "child", "child_key": "iam-roles"},
            {"key": "policies",        "label": "Policies",             "icon": "policy",
                "type": "child", "child_key": "iam-policies"},
            {"key": "providers",       "label": "Identity providers",   "icon": "verified_user",
                "type": "child", "child_key": "iam-providers"},
            {"group": "Reporting"},
            {"key": "access-analyzer", "label": "Access Analyzer",      "icon": "find_in_page", "type": "stub"},
            {"key": "credential-report","label": "Credential report",   "icon": "summarize",    "type": "stub"},
        ],
        "api_paths": {
            "users":      {"method": "GET",    "path": "/api/iam/users"},
            "groups":     {"method": "GET",    "path": "/api/iam/groups"},
            "roles":      {"method": "GET",    "path": "/api/iam/roles"},
            "policies":   {"method": "GET",    "path": "/api/iam/policies"},
            "attachments":{"method": "GET",    "path": "/api/iam/attachments"},
            "deleteUser": {"method": "DELETE", "path": "/api/iam/users/{name}"},
            "deleteRole": {"method": "DELETE", "path": "/api/iam/roles/{name}"},
            "deletePolicy":{"method":"DELETE", "path": "/api/iam/policies/{name}"},
        },
        # v2.0.4: IAM user response doesn't include `arn` — only
        # `user_id` + `user_name`. Show user_id as the second column.
        # The real AWS IAM does include ARN; the simulator's IAM
        # response generation is a v2.1.0 follow-up. For now the SPA
        # surfaces what the backend actually returns.
        "columns": [
            ["user_name", "User name"],
            ["user_id",   "User ID"],
            ["created",   "Created"],
        ],
        "createFields": [
            {"name": "name", "label": "User name", "default": "new-user"},
        ],
        "endpoints": {},
    },
    {
        "key": "rds", "label": "RDS", "icon": "database",
        "namespace": "AWS/RDS", "service": "rds",
        "collection_path": "/api/rds/databases",
        "resource_path":   "/api/rds/databases/{name}",
        "name_field":      "db_instance_identifier",
        "create_method":   "POST",
        "rail_items": [
            {"key": "dashboard",        "label": "Dashboard",            "icon": "dashboard",   "type": "stub"},
            {"key": "databases",        "label": "Databases",            "icon": "database",    "type": "primary"},
            {"key": "snapshots",        "label": "Snapshots",            "icon": "photo_camera","type": "child", "child_key": "snapshots"},
            {"key": "performance",      "label": "Performance Insights", "icon": "insights",    "type": "stub"},
            {"key": "subnet-groups",    "label": "Subnet groups",        "icon": "view_module", "type": "stub"},
            {"key": "param-groups",     "label": "Parameter groups",     "icon": "settings",    "type": "stub"},
            {"key": "option-groups",    "label": "Option groups",        "icon": "tune",        "type": "stub"},
            {"key": "reserved",         "label": "Reserved instances",   "icon": "bookmark",    "type": "stub"},
            {"key": "events",           "label": "Events",               "icon": "event",       "type": "stub"},
        ],
        "api_paths": {
            "start":         {"method": "POST",   "path": "/api/rds/databases/{name}/start"},
            "stop":          {"method": "POST",   "path": "/api/rds/databases/{name}/stop"},
            "reboot":        {"method": "POST",   "path": "/api/rds/databases/{name}/reboot"},
            "modify":        {"method": "POST",   "path": "/api/rds/databases/{name}/modify"},
            "delete":        {"method": "DELETE", "path": "/api/rds/databases/{name}"},
            "snapshots":     {"method": "GET",    "path": "/api/rds/snapshots"},
            "subnetGroups":  {"method": "GET",    "path": "/api/rds/subnet-groups"},
            "paramGroups":   {"method": "GET",    "path": "/api/rds/parameter-groups"},
        },
        "children": [
            {"type": "snapshots", "label": "Snapshots", "icon": "photo_camera"},
        ],
        # v2.0.4: aligned column keys with actual RDS response. Was
        # showing every Class + Endpoint cell as `—` because the
        # response uses `db_instance_class` + `endpoint_address`, not
        # the short forms.
        "columns": [
            ["db_instance_identifier", "Identifier"],
            ["engine",                 "Engine"],
            ["db_instance_class",      "Class"],
            ["status",                 "Status"],
            ["endpoint_address",       "Endpoint"],
        ],
        "createFields": [
            {"name": "name", "label": "DB identifier", "default": "database-1"},
            {"name": "engine", "label": "Engine", "default": "postgres"},
            {"name": "instance_class", "label": "Instance class", "default": "db.t3.micro"},
        ],
        "endpoints": {},
    },
    {
        "key": "dynamodb", "label": "DynamoDB", "icon": "table_chart",
        "namespace": "AWS/DynamoDB", "service": "dynamodb",
        "collection_path": "/api/dynamodb/tables",
        "resource_path":   "/api/dynamodb/tables/{name}",
        "name_field":      "table_name",
        "create_method":   "POST",
        "rail_items": [
            {"key": "dashboard",    "label": "Dashboard",         "icon": "dashboard",   "type": "stub"},
            {"key": "tables",       "label": "Tables",            "icon": "table_chart", "type": "primary"},
            {"key": "indexes",      "label": "Indexes",           "icon": "format_indent_increase","type":"stub"},
            {"key": "backups",      "label": "Backups",           "icon": "backup",      "type": "stub"},
            {"key": "exports",      "label": "Exports to S3",     "icon": "upload",      "type": "stub"},
            {"key": "streams",      "label": "Streams",           "icon": "stream",      "type": "stub"},
            {"key": "dax",          "label": "DAX clusters",      "icon": "speed",       "type": "stub"},
            {"key": "global-tables","label": "Global Tables",     "icon": "public",      "type": "stub"},
        ],
        "api_paths": {
            "items":  {"method": "GET",  "path": "/api/dynamodb/tables/{name}/items"},
            "put":    {"method": "POST", "path": "/api/dynamodb/tables/{name}/items"},
            "query":  {"method": "POST", "path": "/api/dynamodb/tables/{name}/query"},
            "scan":   {"method": "POST", "path": "/api/dynamodb/tables/{name}/scan"},
            "delete": {"method": "DELETE","path": "/api/dynamodb/tables/{name}"},
        },
        # v2.0.4: column keys must match the field names in the actual
        # /api/dynamodb/tables response. Old values (`name`,
        # `partition_key`, `sort_key`) returned undefined → SPA rendered
        # every cell as `—`. Real response uses `table_name`,
        # `partition_key_name`, `sort_key_name`. Caught by the new
        # tests/conformance/ui_real/ Playwright suite.
        "columns": [
            ["table_name",          "Name"],
            ["partition_key_name",  "Partition key"],
            ["sort_key_name",       "Sort key"],
            ["billing_mode",        "Billing mode"],
            ["item_count",          "Items"],
        ],
        "createFields": [
            {"name": "name", "label": "Table name", "default": "MyTable"},
            {"name": "partition_key", "label": "Partition key", "default": "id"},
            {"name": "billing_mode", "label": "Billing mode", "default": "PAY_PER_REQUEST"},
        ],
        "endpoints": {},
    },
    {
        "key": "sqs", "label": "SQS", "icon": "queue",
        "namespace": "AWS/SQS", "service": "sqs",
        "collection_path": "/api/sqs/queues",
        "resource_path":   "/api/sqs/queues/{name}",
        "name_field":      "queue_name",
        "create_method":   "POST",
        "rail_items": [
            {"key": "queues",     "label": "Queues",     "icon": "queue",   "type": "primary"},
            {"key": "dlqs",       "label": "Dead-letter queues", "icon": "warning", "type": "stub"},
        ],
        "api_paths": {
            "send":           {"method": "POST",   "path": "/api/sqs/queues/{name}/send"},
            "receive":        {"method": "POST",   "path": "/api/sqs/queues/{name}/receive"},
            "purge":          {"method": "POST",   "path": "/api/sqs/queues/{name}/purge"},
            "delete":         {"method": "DELETE", "path": "/api/sqs/queues/{name}"},
        },
        # v2.0.4: same fix as DynamoDB — column keys must match the
        # actual /api/sqs/queues response field names. Was `name`/`url`/
        # `arn` → all empty cells. Real keys are `queue_name`,
        # `queue_url`, `queue_arn`.
        "columns": [
            ["queue_name",   "Name"],
            ["queue_type",   "Type"],
            ["queue_url",    "URL"],
            ["queue_arn",    "ARN"],
            ["message_count","Messages"],
        ],
        "createFields": [
            {"name": "name", "label": "Queue name", "default": "MyQueue"},
            {"name": "queue_type", "label": "Type", "default": "Standard"},
        ],
        "endpoints": {},
    },
    {
        "key": "lambda", "label": "Lambda", "icon": "bolt",
        "namespace": "AWS/Lambda", "service": "lambda",
        "collection_path": "/api/lambda/functions",
        "resource_path":   "/api/lambda/functions/{name}",
        "name_field":      "function_name",
        "create_method":   "POST",
        "rail_items": [
            {"key": "dashboard",  "label": "Dashboard",   "icon": "dashboard", "type": "stub"},
            {"key": "functions",  "label": "Functions",   "icon": "bolt",      "type": "primary"},
            {"key": "applications","label": "Applications","icon": "apps",     "type": "stub"},
            {"key": "layers",     "label": "Layers",      "icon": "layers",    "type": "stub"},
            {"key": "code-signing","label": "Code signing","icon": "verified", "type": "stub"},
        ],
        "api_paths": {
            "updateCode":   {"method": "POST",   "path": "/api/lambda/functions/{name}/code"},
            "updateConfig": {"method": "POST",   "path": "/api/lambda/functions/{name}/configuration"},
            "invoke":       {"method": "POST",   "path": "/api/lambda/functions/{name}/invoke"},
            "invocations":  {"method": "GET",    "path": "/api/lambda/functions/{name}/invocations"},
            "permission":   {"method": "POST",   "path": "/api/lambda/functions/{name}/permission"},
            "delete":       {"method": "DELETE", "path": "/api/lambda/functions/{name}"},
        },
        "columns": [
            ["function_name",  "Function name"],
            ["runtime",        "Runtime"],
            ["handler",        "Handler"],
            ["memory_size",    "Memory (MB)"],
            ["timeout",        "Timeout (s)"],
            ["last_modified",  "Last modified"],
        ],
        "createFields": [
            {"name": "name", "label": "Function name", "default": "my-function"},
            {"name": "runtime", "label": "Runtime", "default": "python3.12"},
            {"name": "handler", "label": "Handler", "default": "lambda_function.lambda_handler"},
        ],
        "endpoints": {},
    },
    {
        "key": "apigateway", "label": "API Gateway", "icon": "api",
        "namespace": "AWS/ApiGateway", "service": "apigateway",
        "collection_path": "/api/apigateway/apis",
        "resource_path":   "/api/apigateway/apis/{name}",
        "name_field":      "rest_api_id",
        "create_method":   "POST",
        "rail_items": [
            {"key": "apis",          "label": "APIs",                 "icon": "api",          "type": "primary"},
            {"key": "domains",       "label": "Custom domain names",  "icon": "language",     "type": "stub"},
            {"key": "vpc-links",     "label": "VPC links",            "icon": "lan",          "type": "stub"},
            {"key": "client-certs",  "label": "Client certificates",  "icon": "verified",     "type": "stub"},
            {"key": "usage-plans",   "label": "Usage plans",          "icon": "trending_up",  "type": "stub"},
            {"key": "api-keys",      "label": "API keys",             "icon": "vpn_key",      "type": "stub"},
        ],
        "api_paths": {
            "resources":   {"method": "GET",  "path": "/api/apigateway/apis/{name}/resources"},
            "createResource":{"method":"POST","path":"/api/apigateway/apis/{name}/resources"},
            "putMethod":   {"method": "PUT",  "path": "/api/apigateway/apis/{name}/resources/{rid}/methods/{verb}"},
            "stages":      {"method": "GET",  "path": "/api/apigateway/apis/{name}/stages"},
            "createStage": {"method": "POST", "path": "/api/apigateway/apis/{name}/stages"},
            "createDeploy":{"method": "POST", "path": "/api/apigateway/apis/{name}/deployments"},
            "delete":      {"method": "DELETE","path": "/api/apigateway/apis/{name}"},
        },
        "children": [
            {"type": "resources", "label": "Resources", "icon": "account_tree"},
            {"type": "stages",    "label": "Stages",    "icon": "rocket_launch"},
        ],
        # v2.0.4: API ID column was `id` but real response uses
        # `rest_api_id`. Caught by real-SPA conformance.
        "columns": [
            ["rest_api_id",   "API ID"],
            ["name",          "Name"],
            ["endpoint_type", "Endpoint type"],
            ["created",       "Created"],
        ],
        "createFields": [
            {"name": "name", "label": "API name", "default": "MyApi"},
            {"name": "description", "label": "Description", "default": ""},
        ],
        "endpoints": {},
    },
    {
        # API Gateway V2 — HTTP + WebSocket APIs (core/apigatewayv2_core.py). Console REST
        # at /api/apigatewayv2/*; the native /v2/* wire serves SDKs/CLI off the same store.
        "key": "apigatewayv2", "label": "API Gateway V2", "icon": "api",
        "namespace": "AWS/ApiGatewayV2", "service": "apigatewayv2",
        "collection_path": "/api/apigatewayv2/apis",
        "resource_path":   "/api/apigatewayv2/apis/{name}",
        "name_field":      "api_id",
        "create_method":   "POST",
        "rail_items": [
            {"key": "apis", "label": "HTTP & WebSocket APIs", "icon": "api", "type": "primary"},
        ],
        "api_paths": {
            "routes":       {"method": "GET",    "path": "/api/apigatewayv2/apis/{name}/routes"},
            "integrations": {"method": "GET",    "path": "/api/apigatewayv2/apis/{name}/integrations"},
            "stages":       {"method": "GET",    "path": "/api/apigatewayv2/apis/{name}/stages"},
            "deployments":  {"method": "GET",    "path": "/api/apigatewayv2/apis/{name}/deployments"},
            "authorizers":  {"method": "GET",    "path": "/api/apigatewayv2/apis/{name}/authorizers"},
            "models":       {"method": "GET",    "path": "/api/apigatewayv2/apis/{name}/models"},
            "delete":       {"method": "DELETE", "path": "/api/apigatewayv2/apis/{name}"},
        },
        "children": [],
        "columns": [
            ["api_id",        "API ID"],
            ["name",          "Name"],
            ["protocol_type", "Protocol"],
            ["api_endpoint",  "Invoke URL"],
            ["route_count",   "Routes"],
            ["created",       "Created"],
        ],
        "createFields": [
            {"name": "name", "label": "API name", "default": "my-http-api"},
            {"name": "protocol_type", "label": "Protocol (HTTP or WEBSOCKET)", "default": "HTTP"},
            {"name": "target", "label": "Quick-create target (URL or Lambda ARN)", "default": "https://example.com"},
            {"name": "description", "label": "Description", "default": "Created from the console"},
        ],
        "endpoints": {},
    },
    {
        # Systems Manager — Parameter Store in the console (core/ssm_core.py also serves
        # documents, Run Command, associations, maintenance windows and patch baselines on
        # the native AmazonSSM wire). Console REST at /api/ssm/*, same store as the SDK/CLI.
        "key": "ssm", "label": "Systems Manager", "icon": "settings_suggest",
        "namespace": "AWS/SSM", "service": "ssm",
        "collection_path": "/api/ssm/parameters",
        "resource_path":   "/api/ssm/parameters/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "rail_items": [
            {"key": "parameters", "label": "Parameter Store", "icon": "settings_suggest", "type": "primary"},
        ],
        "api_paths": {
            "history": {"method": "GET",    "path": "/api/ssm/parameters/{name}/history"},
            "delete":  {"method": "DELETE", "path": "/api/ssm/parameters/{name}"},
        },
        "children": [],
        "columns": [
            ["name",          "Name"],
            ["type",          "Type"],
            ["tier",          "Tier"],
            ["version",       "Version"],
            ["data_type",     "Data type"],
            ["last_modified", "Last modified"],
        ],
        "createFields": [
            {"name": "name", "label": "Name", "default": "/vyomi/app/config"},
            {"name": "type", "label": "Type (String, StringList or SecureString)", "default": "String"},
            {"name": "tier", "label": "Tier (Standard or Advanced)", "default": "Standard"},
            {"name": "value", "label": "Value", "default": "hello-from-vyomi"},
            {"name": "description", "label": "Description", "default": "Created from the console"},
        ],
        "editable": True,   # per-row Edit -> PUT resource_path {value} (new parameter version)
        "endpoints": {},
    },
    {
        # Step Functions — state machines + executions (core/stepfunctions_core.py). Console
        # REST at /api/stepfunctions/*; the native AWSStepFunctions.* JSON wire serves
        # SDKs/CLI off the same store.
        "key": "stepfunctions", "label": "Step Functions", "icon": "account_tree",
        "namespace": "AWS/States", "service": "stepfunctions",
        "collection_path": "/api/stepfunctions/machines",
        "resource_path":   "/api/stepfunctions/machines/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "rail_items": [
            {"key": "machines", "label": "State machines", "icon": "account_tree", "type": "primary"},
        ],
        "api_paths": {
            "executions": {"method": "GET",    "path": "/api/stepfunctions/machines/{name}/executions"},
            "versions":   {"method": "GET",    "path": "/api/stepfunctions/machines/{name}/versions"},
            "aliases":    {"method": "GET",    "path": "/api/stepfunctions/machines/{name}/aliases"},
            "delete":     {"method": "DELETE", "path": "/api/stepfunctions/machines/{name}"},
        },
        "children": [],
        "columns": [
            ["name",           "Name"],
            ["type",           "Type"],
            ["status",         "Status"],
            ["state_count",    "States"],
            ["execution_count", "Executions"],
            ["created",        "Created"],
        ],
        "createFields": [
            {"name": "name", "label": "State machine name", "default": "my-state-machine"},
            {"name": "type", "label": "Type (STANDARD or EXPRESS)", "default": "STANDARD"},
            {"name": "role_arn", "label": "Execution role ARN", "default": "arn:aws:iam::000000000000:role/service-role/StepFunctions-ExecutionRole"},
            {"name": "definition", "label": "Definition (Amazon States Language)",
             "default": "{\"Comment\": \"A Hello World example\", \"StartAt\": \"Hello\", \"States\": {\"Hello\": {\"Type\": \"Pass\", \"Result\": \"Hello\", \"Next\": \"World\"}, \"World\": {\"Type\": \"Pass\", \"Result\": \"World\", \"End\": true}}}"},
        ],
        "endpoints": {},
    },
    {
        "key": "vpc", "label": "VPC", "icon": "lan",
        "namespace": "AWS/EC2", "service": "vpc",
        "collection_path": "/api/vpc/vpcs",
        "resource_path":   "/api/vpc/vpcs/{name}",
        "name_field":      "vpc_id",
        "create_method":   "POST",
        "rail_items": [
            {"key": "dashboard",        "label": "VPC Dashboard",        "icon": "dashboard",   "type": "stub"},
            {"group": "Virtual private cloud"},
            {"key": "vpcs",             "label": "Your VPCs",            "icon": "lan",         "type": "primary"},
            {"key": "subnets",          "label": "Subnets",              "icon": "view_module", "type": "child", "child_key": "subnets"},
            {"key": "route-tables",     "label": "Route tables",         "icon": "route",       "type": "child", "child_key": "route-tables"},
            {"key": "internet-gateways","label": "Internet gateways",    "icon": "language",    "type": "child", "child_key": "internet-gateways"},
            {"key": "nat-gateways",     "label": "NAT gateways",         "icon": "swap_horiz",  "type": "stub"},
            {"key": "egress-only-igw",  "label": "Egress-only internet gateways","icon": "logout","type":"stub"},
            {"key": "carrier-gw",       "label": "Carrier gateways",     "icon": "network_node","type": "stub"},
            {"key": "dhcp-options",     "label": "DHCP option sets",     "icon": "dns",         "type": "stub"},
            {"key": "elastic-ips",      "label": "Elastic IPs",          "icon": "public",      "type": "stub"},
            {"key": "endpoints",        "label": "Endpoints",            "icon": "hub",          "type": "stub"},
            {"key": "endpoint-services","label": "Endpoint services",    "icon": "settings_ethernet","type":"stub"},
            {"key": "peering",          "label": "Peering connections",  "icon": "compare_arrows","type": "stub"},
            {"group": "Security"},
            {"key": "sgs",              "label": "Security groups",      "icon": "shield",      "type": "child", "child_key": "security-groups"},
            {"key": "nacls",            "label": "Network ACLs",         "icon": "verified_user","type": "stub"},
            {"group": "Reachability"},
            {"key": "reachability",     "label": "Reachability Analyzer","icon": "find_in_page","type": "stub"},
        ],
        "api_paths": {
            "subnets":           {"method": "GET",  "path": "/api/vpc/subnets"},
            "createSubnet":      {"method": "POST", "path": "/api/vpc/subnets"},
            "securityGroups":    {"method": "GET",  "path": "/api/vpc/security-groups"},
            "createSecurityGroup":{"method":"POST", "path": "/api/vpc/security-groups"},
            "addIngress":        {"method": "POST", "path": "/api/vpc/security-groups/{sg}/ingress"},
            "routeTables":       {"method": "GET",  "path": "/api/vpc/route-tables"},
            "createRouteTable":  {"method": "POST", "path": "/api/vpc/route-tables"},
            "addRoute":          {"method": "POST", "path": "/api/vpc/route-tables/{rtb}/routes"},
            "associateSubnet":   {"method": "POST", "path": "/api/vpc/route-tables/{rtb}/associations"},
            "internetGateways":  {"method": "GET",  "path": "/api/vpc/internet-gateways"},
            "createIgw":         {"method": "POST", "path": "/api/vpc/internet-gateways"},
            "attachIgw":         {"method": "POST", "path": "/api/vpc/internet-gateways/{igw}/attach"},
            "resources":         {"method": "GET",  "path": "/api/vpc/vpcs/{name}/resources"},
            "delete":            {"method": "DELETE","path": "/api/vpc/vpcs/{name}"},
        },
        "children": [
            {"type": "subnets",         "label": "Subnets",          "icon": "view_module"},
            {"type": "security-groups", "label": "Security groups",  "icon": "shield"},
            {"type": "route-tables",    "label": "Route tables",     "icon": "route"},
            {"type": "internet-gateways","label": "Internet gateways","icon": "language"},
        ],
        # v2.0.4: VPC response doesn't return `is_default` — backend
        # treats every VPC as user-created. Replaced with the subnet
        # count which is actually useful to surface.
        "columns": [
            ["vpc_id",            "VPC ID"],
            ["name",              "Name"],
            ["cidr_block",        "IPv4 CIDR"],
            ["state",             "State"],
            ["subnet_count",      "Subnets"],
        ],
        "createFields": [
            {"name": "name", "label": "Name", "default": "my-vpc"},
            {"name": "cidr_block", "label": "IPv4 CIDR", "default": "10.0.0.0/16"},
        ],
        "endpoints": {},
    },
    # ========================================================================
    # EventBridge — event-driven service. Rules are the primary entity.
    # No dedicated backend; routes through /api/aws/extras/eventbridge/...
    # ========================================================================
    {
        "key": "eventbridge", "label": "EventBridge", "icon": "hub",
        "namespace": "AWS/Events", "service": "events",
        "collection_path": "/api/aws/extras/eventbridge/rules",
        "resource_path":   "/api/aws/extras/eventbridge/rules/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "rules":            {"method": "GET",  "path": "/api/aws/extras/eventbridge/rules"},
            "event-buses":      {"method": "GET",  "path": "/api/aws/extras/eventbridge/event-buses"},
            "archives":         {"method": "GET",  "path": "/api/aws/extras/eventbridge/archives"},
            "connections":      {"method": "GET",  "path": "/api/aws/extras/eventbridge/connections"},
            "api-destinations": {"method": "GET",  "path": "/api/aws/extras/eventbridge/api-destinations"},
            "delete":           {"method": "DELETE","path": "/api/aws/extras/eventbridge/rules/{name}"},
        },
        "rail_items": [
            {"key": "rules",            "label": "Rules",            "icon": "rule",          "type": "primary"},
            {"group": "Events"},
            {"key": "buses",            "label": "Event buses",      "icon": "hub",
                "type": "stub", "stub_key": "eventbridge/event-buses"},
            {"key": "archives",         "label": "Archives",         "icon": "inventory",
                "type": "stub", "stub_key": "eventbridge/archives"},
            {"key": "replays",          "label": "Replays",          "icon": "replay",
                "type": "stub", "stub_key": "eventbridge/replays"},
            {"group": "Integration"},
            {"key": "connections",      "label": "Connections",      "icon": "link",
                "type": "stub", "stub_key": "eventbridge/connections"},
            {"key": "api-destinations", "label": "API destinations", "icon": "outbound",
                "type": "stub", "stub_key": "eventbridge/api-destinations"},
            {"key": "endpoints",        "label": "Global endpoints", "icon": "public",
                "type": "stub", "stub_key": "eventbridge/endpoints"},
            {"key": "pipes",            "label": "Pipes",            "icon": "swap_horiz",
                "type": "stub", "stub_key": "eventbridge/pipes"},
            {"group": "Schema registry"},
            {"key": "schema-registries","label": "Schema registries","icon": "schema",
                "type": "stub", "stub_key": "eventbridge/schema-registries"},
        ],
        "columns": [
            ["name",            "Name"],
            ["event_bus_name",  "Event bus"],
            ["rule_type",       "Type"],
            ["state",           "Status"],
            ["target_count",    "Targets"],
        ],
        "createFields": [
            {"name": "name", "label": "Name", "default": "my-rule"},
            {"name": "event_bus_name", "label": "Event bus", "default": "default"},
        ],
        "endpoints": {},
    },
    # ========================================================================
    # CloudWatch Logs — log groups are the primary entity. Engine:
    # core/logs_core.py (same file Nano runs); console REST under /api/logs.
    # ========================================================================
    {
        "key": "logs", "label": "CloudWatch Logs", "icon": "subject",
        "namespace": "AWS/Logs", "service": "logs",
        "collection_path": "/api/logs/log-groups",
        "resource_path":   "/api/logs/log-groups/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "editable":        False,
        "api_paths": {
            "streams":              {"method": "GET", "path": "/api/logs/log-groups/{name}/streams"},
            "events":               {"method": "GET", "path": "/api/logs/log-groups/{name}/events"},
            "metric-filters":       {"method": "GET", "path": "/api/logs/log-groups/{name}/metric-filters"},
            "subscription-filters": {"method": "GET", "path": "/api/logs/log-groups/{name}/subscription-filters"},
            "delete":               {"method": "DELETE", "path": "/api/logs/log-groups/{name}"},
        },
        "rail_items": [
            {"key": "log-groups", "label": "Log groups", "icon": "subject", "type": "primary"},
        ],
        "columns": [
            ["name",                "Log group"],
            ["log_class",           "Log class"],
            ["retention",           "Retention"],
            ["stream_count",        "Log streams"],
            ["metric_filter_count", "Metric filters"],
            ["stored",              "Stored bytes"],
            ["created",             "Creation time"],
        ],
        "createFields": [
            {"name": "name", "label": "Log group name", "default": "/aws/vyomi/my-app"},
            {"name": "retention_in_days", "label": "Retention (days, 0 = never expire)", "default": "30"},
            {"name": "log_group_class", "label": "Log class", "default": "Standard"},
        ],
        "endpoints": {},
    },
    # ========================================================================
    # Secrets Manager — secrets + rotation + replication
    # ========================================================================
    {
        "key": "secretsmanager", "label": "Secrets Manager", "icon": "key",
        "namespace": "AWS/SecretsManager", "service": "secretsmanager",
        "collection_path": "/api/aws/secrets",
        "resource_path":   "/api/aws/secrets/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "secrets":          {"method": "GET",  "path": "/api/aws/secrets"},
            "rotation":         {"method": "GET",  "path": "/api/aws/extras/secretsmanager/rotation"},
            "replicas":         {"method": "GET",  "path": "/api/aws/extras/secretsmanager/replicas"},
            "delete":           {"method": "DELETE","path": "/api/aws/secrets/{name}"},
        },
        "rail_items": [
            {"key": "secrets",          "label": "Secrets",          "icon": "key",           "type": "primary"},
            {"group": "Management"},
            {"key": "rotation",         "label": "Rotation",         "icon": "autorenew",
                "type": "stub", "stub_key": "secretsmanager/rotation"},
            {"key": "replicas",         "label": "Replication",      "icon": "public",
                "type": "stub", "stub_key": "secretsmanager/replicas"},
            {"key": "rotation-functions","label": "Rotation functions","icon": "bolt",
                "type": "stub", "stub_key": "secretsmanager/rotation-functions"},
        ],
        "columns": [
            ["name",            "Secret name"],
            ["secret_type",     "Type"],
            ["last_rotated",    "Last rotated"],
            ["next_rotation",   "Next rotation"],
            ["kms_key_id",      "Encryption key"],
        ],
        "createFields": [
            {"name": "name", "label": "Secret name", "default": "my-secret"},
            {"name": "value", "label": "Secret value", "default": "changeme"},
        ],
        "editable": True,   # per-row Edit -> PUT resource_path {value} (Update)
        "endpoints": {},
    },
    # ========================================================================
    # KMS — keys + aliases + custom key stores
    # ========================================================================
    {
        "key": "kms", "label": "KMS", "icon": "enhanced_encryption",
        "namespace": "AWS/KMS", "service": "kms",
        "collection_path": "/api/aws/kms/keys",
        "resource_path":   "/api/aws/kms/keys/{name}",
        "name_field":      "key_id",
        "create_method":   "POST",
        "api_paths": {
            "keys":              {"method": "GET",  "path": "/api/aws/kms/keys"},
            "aws-managed-keys":  {"method": "GET",  "path": "/api/aws/extras/kms/aws-managed-keys"},
            "aliases":           {"method": "GET",  "path": "/api/aws/extras/kms/aliases"},
            "custom-key-stores": {"method": "GET",  "path": "/api/aws/extras/kms/custom-key-stores"},
            "delete":            {"method": "DELETE","path": "/api/aws/kms/keys/{name}"},
        },
        "rail_items": [
            {"group": "Keys"},
            {"key": "customer-keys", "label": "Customer managed keys", "icon": "key",  "type": "primary"},
            {"key": "aws-managed",   "label": "AWS managed keys",     "icon": "verified",
                "type": "stub", "stub_key": "kms/aws-managed-keys"},
            {"key": "aliases",       "label": "Aliases",              "icon": "label",
                "type": "stub", "stub_key": "kms/aliases"},
            {"group": "Custom key stores"},
            {"key": "ckstores",      "label": "Custom key stores",    "icon": "vpn_lock",
                "type": "stub", "stub_key": "kms/custom-key-stores"},
            {"group": "Reporting"},
            {"key": "audit-events",  "label": "AWS Config events",    "icon": "fact_check",
                "type": "stub", "stub_key": "kms/audit-events"},
        ],
        "columns": [
            ["key_id",      "Key ID"],
            ["alias",       "Alias"],
            ["key_spec",    "Type"],
            ["key_usage",   "Usage"],
            ["state",       "Status"],
            ["created",     "Created"],
        ],
        "createFields": [
            {"name": "name",     "label": "Alias",    "default": "my-kms-key"},
            {"name": "key_spec", "label": "Key spec", "default": "SYMMETRIC_DEFAULT"},
        ],
        "endpoints": {},
    },    # ========================================================================
    # Elastic Load Balancing — application / network / gateway load balancers.
    # Engine: core/elbv2_core.py (native Query wire + this console REST).
    # ========================================================================
    {
        "key": "elbv2", "label": "Elastic Load Balancing", "icon": "alt_route",
        "namespace": "AWS/ApplicationELB", "service": "elbv2",
        "collection_path": "/api/aws/elbv2/load-balancers",
        "resource_path":   "/api/aws/elbv2/load-balancers/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "loadBalancers": {"method": "GET",  "path": "/api/aws/elbv2/load-balancers"},
            "targetGroups":  {"method": "GET",  "path": "/api/aws/elbv2/target-groups"},
            "listeners":     {"method": "GET",  "path": "/api/aws/elbv2/listeners"},
            "delete":        {"method": "DELETE", "path": "/api/aws/elbv2/load-balancers/{name}"},
        },
        "rail_items": [
            {"key": "load-balancers", "label": "Load balancers", "icon": "alt_route", "type": "primary"},
            {"group": "Routing"},
            {"key": "target-groups",  "label": "Target groups",  "icon": "dns",
                "type": "child", "child_key": "target-groups"},
            {"key": "listeners",      "label": "Listeners",      "icon": "hearing",
                "type": "child", "child_key": "listeners"},
        ],
        "children": [
            {"type": "target-groups", "label": "Target groups", "icon": "dns"},
            {"type": "listeners", "label": "Listeners", "icon": "hearing"},
        ],
        "columns": [
            ["name",               "Name"],
            ["dns_name",           "DNS name"],
            ["state",              "State"],
            ["type",               "Type"],
            ["scheme",             "Scheme"],
            ["vpc_id",             "VPC ID"],
            ["availability_zones", "Availability Zones"],
            ["created",            "Date created"],
        ],
        "createFields": [
            {"name": "name", "label": "Load balancer name", "default": "my-alb"},
            {"name": "type", "label": "Type (application, network, gateway)", "default": "application"},
            {"name": "scheme", "label": "Scheme (internet-facing, internal)", "default": "internet-facing"},
        ],
        "endpoints": {},
    },
    # ========================================================================
    # CloudWatch — alarms (metrics, dashboards, streams via the native wire)
    # ========================================================================
    {
        "key": "cloudwatch", "label": "CloudWatch", "icon": "monitoring",
        "namespace": "AWS/CloudWatch", "service": "cloudwatch",
        "collection_path": "/api/aws/cloudwatch/alarms",
        "resource_path":   "/api/aws/cloudwatch/alarms/{name}",
        "name_field":      "name",
        "create_method":   "POST",
        "api_paths": {
            "alarms": {"method": "GET",    "path": "/api/aws/cloudwatch/alarms"},
            "delete": {"method": "DELETE", "path": "/api/aws/cloudwatch/alarms/{name}"},
        },
        "rail_items": [
            {"key": "alarms", "label": "Alarms", "icon": "notifications_active", "type": "primary"},
        ],
        "columns": [
            ["name",      "Alarm name"],
            ["state",     "State"],
            ["metric",    "Metric"],
            ["condition", "Conditions"],
            ["period",    "Period"],
            ["actions",   "Actions"],
            ["updated",   "Last state update"],
        ],
        "createFields": [
            {"name": "name", "label": "Alarm name", "default": "my-alarm"},
            {"name": "namespace", "label": "Namespace", "default": "AWS/EC2"},
            {"name": "metric_name", "label": "Metric name", "default": "CPUUtilization"},
            {"name": "dimensions", "label": "Dimensions (Name=Value, ...)", "default": "InstanceId=i-0abcd1234efgh5678"},
            {"name": "statistic", "label": "Statistic", "default": "Average"},
            {"name": "period", "label": "Period (seconds)", "default": "300"},
            {"name": "threshold", "label": "Threshold", "default": "80"},
            {"name": "comparison_operator", "label": "Comparison operator", "default": "GreaterThanOrEqualToThreshold"},
            {"name": "evaluation_periods", "label": "Evaluation periods", "default": "1"},
            {"name": "alarm_action", "label": "Alarm action (SNS topic ARN)", "default": "arn:aws:sns:us-east-1:123456789012:alerts"},
        ],
        "endpoints": {},
    },
    # ========================================================================
    # Amazon SES (v2) — verified identities, configuration sets, templates,
    # contact lists, suppression list. Engine: core/sesv2_core.py (native
    # REST-JSON wire + this console REST); mail is really delivered to Mailpit offline.
    # ========================================================================
    {
        "key": "sesv2", "label": "Amazon SES", "icon": "mail",
        "namespace": "AWS/SES", "service": "sesv2",
        "collection_path": "/api/aws/sesv2/identities",
        "resource_path":   "/api/aws/sesv2/identities/{name}",
        "name_field":      "identity",
        "create_method":   "POST",
        "api_paths": {
            "identities":         {"method": "GET",  "path": "/api/aws/sesv2/identities"},
            "configuration-sets": {"method": "GET",  "path": "/api/aws/sesv2/configuration-sets"},
            "templates":          {"method": "GET",  "path": "/api/aws/sesv2/templates"},
            "contact-lists":      {"method": "GET",  "path": "/api/aws/sesv2/contact-lists"},
            "suppression":        {"method": "GET",  "path": "/api/aws/sesv2/suppression"},
            "sent-emails":        {"method": "GET",  "path": "/api/aws/sesv2/sent-emails"},
            "received-emails":    {"method": "GET",  "path": "/api/aws/sesv2/received-emails"},
            "mail-settings":      {"method": "GET",  "path": "/api/aws/sesv2/mail-settings"},
            "delete":             {"method": "DELETE", "path": "/api/aws/sesv2/identities/{name}"},
        },
        "rail_items": [
            {"key": "identities", "label": "Verified identities", "icon": "verified_user", "type": "primary"},
            {"group": "Configuration"},
            {"key": "configuration-sets", "label": "Configuration sets", "icon": "tune",
                "type": "child", "child_key": "configuration-sets"},
            {"key": "templates", "label": "Email templates", "icon": "article",
                "type": "child", "child_key": "templates"},
            {"key": "contact-lists", "label": "Contact lists", "icon": "contacts",
                "type": "child", "child_key": "contact-lists"},
            {"group": "Reputation & activity"},
            {"key": "suppression", "label": "Suppression list", "icon": "block",
                "type": "child", "child_key": "suppression"},
            {"key": "sent-emails", "label": "Sent emails", "icon": "outbox",
                "type": "child", "child_key": "sent-emails"},
            {"key": "received-emails", "label": "Received emails", "icon": "move_to_inbox",
                "type": "child", "child_key": "received-emails"},
            {"group": "Mail delivery"},
            {"key": "mail-settings", "label": "Delivery settings", "icon": "settings_ethernet",
                "type": "child", "child_key": "mail-settings"},
        ],
        "children": [
            {"type": "configuration-sets", "label": "Configuration sets", "icon": "tune"},
            {"type": "templates", "label": "Email templates", "icon": "article"},
            {"type": "contact-lists", "label": "Contact lists", "icon": "contacts"},
            {"type": "suppression", "label": "Suppression list", "icon": "block"},
            {"type": "sent-emails", "label": "Sent emails", "icon": "outbox"},
            {"type": "received-emails", "label": "Received emails", "icon": "move_to_inbox"},
            {"type": "mail-settings", "label": "Delivery settings", "icon": "settings_ethernet"},
        ],
        "columns": [
            ["identity",   "Identity"],
            ["type",       "Identity type"],
            ["status",     "Identity status"],
            ["sending",    "Sending status"],
            ["dkim",       "DKIM"],
            ["mail_from",  "Custom MAIL FROM domain"],
            ["config_set", "Default configuration set"],
            ["region",     "Region"],
        ],
        "createFields": [
            {"name": "name",       "label": "Identity (domain or email address)", "default": "noreply@vyomi.example.com"},
            {"name": "config_set", "label": "Default configuration set",          "default": "Not set"},
        ],
        "endpoints": {},
    },
]

_BY_KEY = {c["key"]: c for c in RESOURCE_CATALOG_AWS}


def catalog_for_console() -> list[dict]:
    """Return the AWS catalog augmented with wizard + sub-blade schemas for
    the standalone /console/aws SPA. Same shape as
    ``providers.azure_services.catalog_for_console``."""
    from core.aws_wizards import WIZARDS
    from core.aws_subblades import SUB_BLADES
    out = []
    for c in RESOURCE_CATALOG_AWS:
        entry = {
            "key": c["key"], "label": c["label"], "icon": c["icon"],
            "namespace": c["namespace"], "service": c["service"],
            "collection_path": c["collection_path"],
            "resource_path":   c["resource_path"],
            "name_field":      c["name_field"],
            "create_method":   c["create_method"],
            # create_path is optional — only set for services where the
            # POST endpoint doesn't match collection_path (S3: bucket
            # name nested in the path). Console renderer falls back to
            # collection_path when this is absent.
            "create_path":     c.get("create_path"),
            "api_paths":       c["api_paths"],
            "columns":         c["columns"],
            "createFields":    c["createFields"],
            "children":        c.get("children", []),
            # Per-service left rail — frontend prefers this over `children`.
            "rail_items":      c.get("rail_items", []),
            # Per-row Edit (Update) — console PUTs {value} to resource_path.
            "editable":        c.get("editable", False),
        }
        if c["key"] in WIZARDS:
            entry["wizard"] = WIZARDS[c["key"]]
        if c["key"] in SUB_BLADES:
            entry["subBlades"] = SUB_BLADES[c["key"]]
        out.append(entry)
    return out


def build_console_payload(active_region: str = "us-east-1",
                          active_account: str = "123456789012") -> dict:
    """Full payload returned by /api/aws/catalog — mirrors Azure's shape so
    the standalone SPA can boot from a single fetch. `extras` carries the
    schemas for stub rail items handled by the generic /api/aws/extras
    backend (Launch Templates, Volumes, Snapshots, …)."""
    from core.aws_rail_extras import EXTRAS
    # Strip the seed data from the payload — frontend doesn't need it (the
    # backend seeds on first GET). Keeps the catalog small.
    slim_extras = {k: {**v, "seed": None} for k, v in EXTRAS.items()}
    return {
        "account": active_account,
        "region":  active_region,
        "services": catalog_for_console(),
        "extras":   slim_extras,
    }
