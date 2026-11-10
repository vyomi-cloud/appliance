"""Schemas for AWS console rail items that don't have first-class backend
support yet. Each entry under EXTRAS is keyed by ``"<service>/<stub-key>"``
(matching the rail_items keys in providers/aws_catalog.py).

Three categories drive different frontend renderers:

* ``crud``      → list page with checkbox column + Create + Delete (default).
                  Backed by the generic /api/aws/extras endpoint family which
                  persists per-space.
* ``analytics`` → read-only synthesized view (events log, performance charts,
                  dashboard tiles, etc.). Items load once from seed.
* ``config``    → single editable record (Block Public Access, etc.). PUT
                  replaces; no Delete.

For stubs whose items genuinely derive from other resources (Network
Interfaces from EC2 instances, DLQs from SQS queues, Subnet Groups from VPC
subnets), the schema sets ``derived_from`` so the backend computes on the
fly instead of using stored items.
"""
from __future__ import annotations


# ---------- shorthand constructors ------------------------------------------

def crud(label, icon, description, columns, create_fields, seed=None, derived_from=None):
    return {"label": label, "icon": icon, "category": "crud",
            "description": description, "columns": columns,
            "create_fields": create_fields, "seed": seed or [],
            "derived_from": derived_from}


def analytics(label, icon, description, columns, seed=None, derived_from=None, sparklines=None):
    return {"label": label, "icon": icon, "category": "analytics",
            "description": description, "columns": columns or [],
            "seed": seed or [], "derived_from": derived_from,
            "sparklines": sparklines or []}


def config(label, icon, description, fields, defaults):
    return {"label": label, "icon": icon, "category": "config",
            "description": description, "fields": fields, "defaults": defaults}


# ---------- common column shapes (kept compact) -----------------------------

_TIME = "2025-11-01T12:00:00Z"


# ============================================================================
# EC2
# ============================================================================
_EC2 = {
    "events": analytics(
        "Events", "event",
        "Account events affecting your EC2 resources (instance status changes, scheduled maintenance, etc.).",
        [["event_id","Event ID"],["instance_id","Resource"],["category","Category"],
         ["description","Description"],["status","Status"],["scheduled","Scheduled"]],
        seed=[
            {"event_id":"evt-001","instance_id":"i-0abc1234","category":"instance-status",
             "description":"Instance status check failed","status":"completed","scheduled":_TIME},
            {"event_id":"evt-002","instance_id":"(account)","category":"system-maintenance",
             "description":"Scheduled platform retirement","status":"upcoming","scheduled":"2025-12-15T00:00:00Z"},
        ]),
    "tag-editor": crud(
        "Tag Editor", "sell",
        "Find and edit tags across multiple AWS resources at once.",
        [["resource","Resource"],["service","Service"],["region","Region"],["tag_keys","Tag keys"]],
        [{"name":"resource","label":"Resource ID/ARN","required":True},
         {"name":"service","label":"Service","default":"ec2"},
         {"name":"tag_keys","label":"Tag keys (comma-separated)","default":"env,owner"}]),
    "instance-types": analytics(
        "Instance Types", "tune",
        "All available EC2 instance types in this Region. Use as reference when picking sizes during launch.",
        [["name","Type"],["vcpu","vCPUs"],["ram_gb","Memory"],["family","Family"],["network","Network performance"]],
        derived_from="ec2:instance-types"),
    "launch-templates": crud(
        "Launch Templates", "rocket_launch",
        "Reusable templates with instance configuration, applied at launch.",
        [["name","Name"],["latest_version","Latest version"],["default_version","Default version"],["created","Created"]],
        [{"name":"name","label":"Template name","required":True,"validate":{"regex":r"^[A-Za-z0-9-_]{3,128}$","message":"3-128 chars"}},
         {"name":"ami_id","label":"AMI ID","default":"ami-amzn2023-x86_64"},
         {"name":"instance_type","label":"Instance type","default":"t3.micro"},
         {"name":"key_name","label":"Key pair name"}],
        seed=[{"name":"web-server-template","latest_version":"3","default_version":"1","created":_TIME,
               "ami_id":"ami-amzn2023-x86_64","instance_type":"t3.medium"}]),
    "spot-requests": crud(
        "Spot Requests", "bolt",
        "Spot instance requests in this Region.",
        [["request_id","Request ID"],["state","State"],["status","Status"],
         ["instance_type","Instance type"],["max_price","Max price ($/hr)"],["created","Created"]],
        [{"name":"instance_type","label":"Instance type","default":"t3.medium","required":True},
         {"name":"max_price","label":"Max price ($/hr)","type":"number","default":0.05,"validate":{"min":0.001,"max":10}},
         {"name":"count","label":"Target capacity","type":"number","default":1,"validate":{"min":1,"max":100}}]),
    "ami-catalog": analytics(
        "AMI Catalog", "view_list",
        "Curated Amazon and AWS Marketplace AMIs available in this Region.",
        [["image_id","AMI ID"],["name","Name"],["platform","Platform"],
         ["architecture","Architecture"],["owner","Owner"]],
        derived_from="ec2:amis"),
    "volumes": crud(
        "Volumes (EBS)", "storage",
        "Block storage volumes available to EC2 instances.",
        [["volume_id","Volume ID"],["state","State"],["size_gb","Size (GiB)"],
         ["volume_type","Type"],["iops","IOPS"],["availability_zone","Availability Zone"],
         ["attached_instance","Attached instance"]],
        [{"name":"size_gb","label":"Size (GiB)","type":"number","default":8,"validate":{"min":1,"max":16384},"required":True},
         {"name":"volume_type","label":"Volume type","type":"select","default":"gp3",
          "options":[{"value":"gp3","label":"gp3 (General Purpose SSD)"},
                     {"value":"gp2","label":"gp2"},
                     {"value":"io2","label":"io2 (Provisioned IOPS SSD)"},
                     {"value":"st1","label":"st1 (Throughput Optimized HDD)"},
                     {"value":"sc1","label":"sc1 (Cold HDD)"}]},
         {"name":"availability_zone","label":"Availability Zone","default":"us-east-1a"},
         {"name":"iops","label":"IOPS","type":"number","default":3000,"validate":{"min":100,"max":256000}}],
        seed=[
            {"volume_id":"vol-0a1b2c3d","state":"in-use","size_gb":30,"volume_type":"gp3","iops":3000,
             "availability_zone":"us-east-1a","attached_instance":"i-0abc1234"},
            {"volume_id":"vol-0e4f5g6h","state":"available","size_gb":100,"volume_type":"gp3","iops":3000,
             "availability_zone":"us-east-1b","attached_instance":"—"},
            {"volume_id":"vol-0i7j8k9l","state":"in-use","size_gb":500,"volume_type":"io2","iops":10000,
             "availability_zone":"us-east-1a","attached_instance":"i-0def5678"},
        ]),
    "snapshots": crud(
        "Snapshots (EBS)", "photo_camera",
        "Point-in-time copies of EBS volumes, stored in S3.",
        [["snapshot_id","Snapshot ID"],["volume_id","Volume"],["size_gb","Size (GiB)"],
         ["state","State"],["progress","Progress"],["started","Started"]],
        [{"name":"volume_id","label":"Source volume","default":"vol-0a1b2c3d","required":True},
         {"name":"description","label":"Description","default":"Manual snapshot"}],
        seed=[
            {"snapshot_id":"snap-0aaa111","volume_id":"vol-0a1b2c3d","size_gb":30,
             "state":"completed","progress":"100%","started":_TIME,"description":"Pre-upgrade backup"},
            {"snapshot_id":"snap-0bbb222","volume_id":"vol-0e4f5g6h","size_gb":100,
             "state":"completed","progress":"100%","started":_TIME,"description":"Weekly backup"},
        ]),
    "elastic-ips": crud(
        "Elastic IPs", "public",
        "Static public IPv4 addresses you can attach to instances and network interfaces.",
        [["allocation_id","Allocation ID"],["public_ip","Public IPv4"],
         ["private_ip","Private IPv4"],["associated_with","Associated with"],["domain","Domain"]],
        [{"name":"description","label":"Tag: Name","default":"my-eip"}],
        seed=[
            {"allocation_id":"eipalloc-0a1","public_ip":"54.210.10.1","private_ip":"10.0.1.50",
             "associated_with":"i-0abc1234","domain":"vpc"},
            {"allocation_id":"eipalloc-0b2","public_ip":"54.210.10.2","private_ip":"—",
             "associated_with":"—","domain":"vpc"},
        ]),
    "key-pairs": crud(
        "Key Pairs", "vpn_key",
        "SSH/RDP key pairs you can use to connect to instances.",
        [["key_pair_id","Key pair ID"],["name","Name"],["type","Type"],
         ["fingerprint","Fingerprint"],["created","Created"]],
        [{"name":"name","label":"Key pair name","required":True,
          "validate":{"regex":r"^[A-Za-z0-9-_]{1,255}$","message":"1-255 chars"}},
         {"name":"type","label":"Key type","type":"select","default":"rsa",
          "options":[{"value":"rsa","label":"RSA"},{"value":"ed25519","label":"ED25519"}]},
         {"name":"format","label":"Private key format","type":"select","default":"pem",
          "options":[{"value":"pem","label":"PEM (OpenSSH)"},{"value":"ppk","label":"PPK (PuTTY)"}]}],
        seed=[{"key_pair_id":"key-0aaa","name":"default-key","type":"rsa",
               "fingerprint":"a1:b2:c3:d4:e5:f6:01:02:03:04:05:06:07:08:09:0a","created":_TIME}]),
    "network-ifs": analytics(
        "Network Interfaces", "lan",
        "Virtual network interfaces attached to EC2 instances. One per primary network attachment.",
        [["interface_id","Interface ID"],["description","Description"],["instance_id","Instance"],
         ["private_ip","Primary private IP"],["public_ip","Public IP"],["subnet_id","Subnet"],["status","Status"]],
        derived_from="ec2:network-interfaces"),
    "load-balancers": crud(
        "Load Balancers", "balance",
        "Application, Network, and Gateway load balancers in this Region.",
        [["name","Name"],["dns_name","DNS name"],["state","State"],
         ["type","Type"],["scheme","Scheme"],["vpc_id","VPC"]],
        [{"name":"name","label":"Load balancer name","required":True,
          "validate":{"regex":r"^[A-Za-z0-9-]{1,32}$","message":"1-32 chars, alphanumerics + hyphens"}},
         {"name":"type","label":"Type","type":"select","default":"application",
          "options":[{"value":"application","label":"Application Load Balancer"},
                     {"value":"network","label":"Network Load Balancer"},
                     {"value":"gateway","label":"Gateway Load Balancer"}]},
         {"name":"scheme","label":"Scheme","type":"select","default":"internet-facing",
          "options":[{"value":"internet-facing","label":"Internet-facing"},
                     {"value":"internal","label":"Internal"}]},
         {"name":"vpc_id","label":"VPC","default":"vpc-default"}],
        seed=[{"name":"web-alb","dns_name":"web-alb-1234567890.us-east-1.elb.amazonaws.com",
               "state":"active","type":"application","scheme":"internet-facing","vpc_id":"vpc-default"}]),
    "target-groups": crud(
        "Target Groups", "ads_click",
        "Target groups define how a load balancer routes requests to registered targets.",
        [["name","Name"],["protocol","Protocol"],["port","Port"],
         ["target_type","Target type"],["vpc_id","VPC"],["healthy_targets","Healthy"]],
        [{"name":"name","label":"Target group name","required":True},
         {"name":"protocol","label":"Protocol","type":"select","default":"HTTP",
          "options":[{"value":"HTTP","label":"HTTP"},{"value":"HTTPS","label":"HTTPS"},
                     {"value":"TCP","label":"TCP"},{"value":"UDP","label":"UDP"},
                     {"value":"TLS","label":"TLS"}]},
         {"name":"port","label":"Port","type":"number","default":80,"validate":{"min":1,"max":65535}},
         {"name":"target_type","label":"Target type","type":"select","default":"instance",
          "options":[{"value":"instance","label":"Instances"},{"value":"ip","label":"IP addresses"},
                     {"value":"lambda","label":"Lambda function"}]}],
        seed=[{"name":"web-targets","protocol":"HTTP","port":80,"target_type":"instance",
               "vpc_id":"vpc-default","healthy_targets":"2 / 2"}]),
    "asg": crud(
        "Auto Scaling Groups", "auto_awesome",
        "Auto Scaling groups automatically launch and terminate instances based on policies.",
        [["name","Name"],["launch_template","Launch template"],["min","Min"],
         ["max","Max"],["desired","Desired"],["instances","Instances"]],
        [{"name":"name","label":"ASG name","required":True},
         {"name":"launch_template","label":"Launch template","default":"web-server-template"},
         {"name":"min","label":"Min size","type":"number","default":1,"validate":{"min":0,"max":1000}},
         {"name":"max","label":"Max size","type":"number","default":3,"validate":{"min":0,"max":1000}},
         {"name":"desired","label":"Desired capacity","type":"number","default":2,"validate":{"min":0,"max":1000}}]),
}


# ============================================================================
# S3
# ============================================================================
_S3 = {
    "directory": crud(
        "Directory buckets", "folder_special",
        "S3 directory buckets store data using S3 Express One Zone storage class for high-throughput workloads.",
        [["name","Name"],["region","Region"],["az","Availability Zone"],["created","Created"]],
        [{"name":"name","label":"Bucket name","required":True,
          "validate":{"regex":r"^[a-z0-9.-]{3,63}--[a-z0-9-]+-x-s3$",
                      "message":"Must follow pattern <name>--<az>--x-s3"}},
         {"name":"az","label":"Availability Zone","default":"use1-az5"}]),
    "table-buckets": crud(
        "Table buckets", "table_chart",
        "S3 table buckets store analytics data in Apache Iceberg format for SQL querying.",
        [["name","Name"],["region","Region"],["tables","Tables"],["created","Created"]],
        [{"name":"name","label":"Table bucket name","required":True}]),
    "access-points": crud(
        "Access Points", "hub",
        "Network-aware access points simplify managing access to shared S3 datasets.",
        [["name","Name"],["bucket","Bucket"],["network_origin","Network origin"],
         ["vpc_id","VPC"],["created","Created"]],
        [{"name":"name","label":"Access point name","required":True,
          "validate":{"regex":r"^[a-z0-9-]{3,50}$","message":"3-50 chars, lowercase"}},
         {"name":"bucket","label":"Bucket","required":True},
         {"name":"network_origin","label":"Network origin","type":"select","default":"Internet",
          "options":[{"value":"Internet","label":"Internet"},{"value":"VPC","label":"VPC"}]}],
        seed=[{"name":"data-team-ap","bucket":"my-bucket-cloudlearn","network_origin":"Internet",
               "vpc_id":"—","created":_TIME}]),
    "mrap": crud(
        "Multi-Region Access Points", "public",
        "Single global endpoint that routes requests to the bucket with lowest latency.",
        [["name","Name"],["alias","Alias"],["regions","Regions"],["status","Status"]],
        [{"name":"name","label":"Multi-Region Access Point name","required":True},
         {"name":"regions","label":"Regions (comma-separated)","default":"us-east-1,eu-west-1"}]),
    "batch-ops": crud(
        "Batch Operations", "playlist_play",
        "Batch jobs that perform large-scale actions on lists of S3 objects.",
        [["job_id","Job ID"],["operation","Operation"],["status","Status"],
         ["priority","Priority"],["progress","Progress"],["created","Created"]],
        [{"name":"operation","label":"Operation","type":"select","default":"Copy",
          "options":[{"value":"Copy","label":"Copy objects"},
                     {"value":"Replace tags","label":"Replace tags"},
                     {"value":"Delete","label":"Delete objects"},
                     {"value":"Restore","label":"Restore from Glacier"}]},
         {"name":"manifest","label":"Manifest object","default":"s3://my-bucket/manifest.csv"}]),
    "storage-lens": analytics(
        "Storage Lens", "monitoring",
        "S3 Storage Lens provides organization-wide visibility into object storage usage and activity.",
        [["dashboard","Dashboard"],["scope","Scope"],["status","Status"],["last_updated","Last updated"]],
        seed=[{"dashboard":"default-account-dashboard","scope":"Entire account",
               "status":"Active","last_updated":_TIME}],
        sparklines=[["Total storage (TB)",5,15,""],
                    ["Total object count",10000,50000,""],
                    ["Buckets",1,20,""]]),
    "block-public": config(
        "Block Public Access (account)", "shield",
        "Account-level S3 Block Public Access settings. These apply on top of bucket and access-point settings.",
        [{"name":"block_public_acls","label":"Block public access granted through new ACLs","type":"boolean","default":True},
         {"name":"ignore_public_acls","label":"Block public access granted through any ACLs","type":"boolean","default":True},
         {"name":"block_public_policy","label":"Block public access granted through new public bucket or access point policies","type":"boolean","default":True},
         {"name":"restrict_public_buckets","label":"Block public and cross-account access to buckets and objects through any public bucket or access point policies","type":"boolean","default":True}],
        defaults={"block_public_acls":True,"ignore_public_acls":True,
                  "block_public_policy":True,"restrict_public_buckets":True}),
}


# ============================================================================
# IAM
# ============================================================================
_IAM = {
    "dashboard": analytics(
        "IAM Dashboard", "dashboard",
        "Snapshot of IAM resources and security recommendations for your account.",
        [["metric","Metric"],["value","Value"],["recommendation","Recommendation"]],
        derived_from="iam:dashboard",
        sparklines=[["Active users (30d)",2,15,""],
                    ["Console logins (7d)",10,80,""],
                    ["API calls (24h)",100,1000,""]]),
    "access-analyzer": analytics(
        "Access Analyzer", "find_in_page",
        "IAM Access Analyzer identifies resources shared with external principals.",
        [["finding_id","Finding ID"],["resource","Resource"],["resource_type","Resource type"],
         ["external_principal","External principal"],["status","Status"],["severity","Severity"]],
        seed=[
            {"finding_id":"fnd-001","resource":"arn:aws:s3:::my-bucket-cloudlearn","resource_type":"AWS::S3::Bucket",
             "external_principal":"*","status":"active","severity":"medium"},
        ]),
    "credential-report": analytics(
        "Credential report", "summarize",
        "Last credential report for IAM users in this account.",
        [["user","User"],["password_enabled","Password enabled"],["password_last_used","Last sign-in"],
         ["mfa_active","MFA active"],["access_key_1_active","Access key 1"],["access_key_1_last_used","Key 1 last used"]],
        seed=[
            {"user":"root","password_enabled":"yes","password_last_used":"2025-10-15","mfa_active":"yes",
             "access_key_1_active":"no","access_key_1_last_used":"N/A"},
            {"user":"deploy-bot","password_enabled":"no","password_last_used":"N/A","mfa_active":"no",
             "access_key_1_active":"yes","access_key_1_last_used":_TIME},
        ]),
}


# ============================================================================
# RDS
# ============================================================================
_RDS = {
    "dashboard": analytics(
        "RDS Dashboard", "dashboard",
        "Overview of your RDS databases and recent activity.",
        [["metric","Metric"],["value","Value"]],
        derived_from="rds:dashboard",
        sparklines=[["Total DB instances",1,5,""],
                    ["Storage used (GiB)",10,300,""],
                    ["Recent backups (7d)",2,8,""]]),
    "performance": analytics(
        "Performance Insights", "insights",
        "Database load and top SQL queries across your DB instances.",
        [["timeframe","Timeframe"],["top_wait","Top wait"],["top_sql","Top SQL"],["avg_load","Avg load"]],
        seed=[{"timeframe":"Last 1 hour","top_wait":"CPU","top_sql":"SELECT * FROM orders WHERE...","avg_load":"0.85"}],
        sparklines=[["DB load (sessions)",0,3,""],
                    ["CPU utilization (%)",10,80,"%"],
                    ["Read IOPS",50,500,""]]),
    "subnet-groups": crud(
        "Subnet groups", "view_module",
        "Collections of subnets that RDS uses to place DB instances in a VPC.",
        [["name","Name"],["description","Description"],["vpc_id","VPC"],
         ["subnets","Subnets"],["status","Status"]],
        [{"name":"name","label":"Name","required":True,
          "validate":{"regex":r"^[a-z][a-z0-9-]{0,254}$","message":"lowercase, start with letter"}},
         {"name":"description","label":"Description","required":True,"default":"DB subnet group"},
         {"name":"vpc_id","label":"VPC","default":"vpc-default"}],
        seed=[{"name":"default","description":"default","vpc_id":"vpc-default",
               "subnets":"subnet-aaa, subnet-bbb","status":"Complete"}]),
    "param-groups": crud(
        "Parameter groups", "settings",
        "Engine-specific configuration parameters applied to DB instances.",
        [["name","Name"],["family","Family"],["type","Type"],["description","Description"]],
        [{"name":"name","label":"Group name","required":True},
         {"name":"family","label":"Family","type":"select","default":"postgres16",
          "options":[{"value":"postgres16","label":"postgres16"},
                     {"value":"postgres15","label":"postgres15"},
                     {"value":"mysql8.0","label":"mysql8.0"},
                     {"value":"mariadb10.11","label":"mariadb10.11"}]},
         {"name":"description","label":"Description","required":True}],
        seed=[{"name":"default.postgres16","family":"postgres16","type":"DB parameter group",
               "description":"Default parameter group for PostgreSQL 16"}]),
    "option-groups": crud(
        "Option groups", "tune",
        "Engine-specific feature options applied to DB instances.",
        [["name","Name"],["engine","Engine"],["major_version","Major version"],["description","Description"]],
        [{"name":"name","label":"Group name","required":True},
         {"name":"engine","label":"Engine","default":"postgres"},
         {"name":"major_version","label":"Major version","default":"16"},
         {"name":"description","label":"Description","required":True}],
        seed=[{"name":"default:postgres-16","engine":"postgres","major_version":"16",
               "description":"Default option group for PostgreSQL 16"}]),
    "reserved": crud(
        "Reserved instances", "bookmark",
        "Capacity reservations that provide a discount over on-demand pricing.",
        [["id","Reserved ID"],["db_instance_class","Class"],["engine","Engine"],
         ["term","Term"],["start_time","Start"],["state","State"]],
        [{"name":"db_instance_class","label":"DB instance class","default":"db.t3.medium"},
         {"name":"engine","label":"Engine","default":"postgres"},
         {"name":"term","label":"Term","type":"select","default":"1-year",
          "options":[{"value":"1-year","label":"1 year"},{"value":"3-year","label":"3 years"}]}]),
    "events": analytics(
        "Events", "event",
        "Recent RDS events for DB instances, snapshots, and parameter groups.",
        [["source","Source"],["source_type","Source type"],["category","Category"],
         ["message","Message"],["date","Date"]],
        seed=[
            {"source":"database-1","source_type":"db-instance","category":"backup",
             "message":"Automated backup created","date":_TIME},
            {"source":"database-1","source_type":"db-instance","category":"maintenance",
             "message":"Database instance restarted","date":_TIME},
        ]),
}


# ============================================================================
# DynamoDB
# ============================================================================
_DYNAMO = {
    "dashboard": analytics(
        "DynamoDB Dashboard", "dashboard",
        "Account-level view of DynamoDB usage and activity.",
        [["metric","Metric"],["value","Value"]],
        derived_from="dynamodb:dashboard",
        sparklines=[["Total tables",1,10,""],
                    ["Items stored (M)",0.1,5,""],
                    ["Read capacity used",10,1000,""]]),
    "indexes": crud(
        "Indexes", "format_indent_increase",
        "Global and Local Secondary Indexes across all your tables.",
        [["table","Table"],["index_name","Index name"],["type","Type"],
         ["partition_key","Partition key"],["projection","Projection"]],
        [{"name":"table","label":"Table","required":True},
         {"name":"index_name","label":"Index name","required":True},
         {"name":"partition_key","label":"Partition key","required":True,"default":"userId"},
         {"name":"projection","label":"Projection","type":"select","default":"ALL",
          "options":[{"value":"ALL","label":"All attributes"},
                     {"value":"KEYS_ONLY","label":"Keys only"},
                     {"value":"INCLUDE","label":"Include selected attributes"}]}]),
    "backups": crud(
        "Backups", "backup",
        "On-demand and continuous backups of your DynamoDB tables.",
        [["name","Backup name"],["table","Source table"],["type","Type"],
         ["status","Status"],["size_bytes","Size"],["created","Created"]],
        [{"name":"name","label":"Backup name","required":True},
         {"name":"table","label":"Source table","required":True}]),
    "exports": crud(
        "Exports to S3", "upload",
        "Continuous and on-demand exports of table data to S3.",
        [["arn","Export ARN"],["table","Source table"],["destination","S3 destination"],
         ["status","Status"],["started","Started"]],
        [{"name":"table","label":"Source table","required":True},
         {"name":"destination","label":"S3 destination","required":True,"default":"s3://my-bucket/exports/"}]),
    "streams": crud(
        "Streams", "stream",
        "DynamoDB Streams capture item-level changes for replication or processing.",
        [["table","Table"],["stream_arn","Stream ARN"],["view_type","View type"],["status","Status"]],
        [{"name":"table","label":"Table","required":True},
         {"name":"view_type","label":"View type","type":"select","default":"NEW_AND_OLD_IMAGES",
          "options":[{"value":"NEW_AND_OLD_IMAGES","label":"New and old images"},
                     {"value":"NEW_IMAGE","label":"New image"},
                     {"value":"OLD_IMAGE","label":"Old image"},
                     {"value":"KEYS_ONLY","label":"Keys only"}]}]),
    "dax": crud(
        "DAX clusters", "speed",
        "DynamoDB Accelerator (DAX) clusters provide microsecond read/write latency for cached items.",
        [["name","Cluster name"],["node_type","Node type"],["status","Status"],
         ["total_nodes","Total nodes"],["active_nodes","Active nodes"]],
        [{"name":"name","label":"Cluster name","required":True},
         {"name":"node_type","label":"Node type","type":"select","default":"dax.r4.large",
          "options":[{"value":"dax.r4.large","label":"dax.r4.large"},
                     {"value":"dax.r4.xlarge","label":"dax.r4.xlarge"},
                     {"value":"dax.r5.large","label":"dax.r5.large"}]},
         {"name":"total_nodes","label":"Total nodes","type":"number","default":3,"validate":{"min":1,"max":10}}]),
    "global-tables": crud(
        "Global Tables", "public",
        "Multi-active, multi-region replicated DynamoDB tables.",
        [["name","Table"],["regions","Regions"],["status","Status"]],
        [{"name":"name","label":"Table name","required":True},
         {"name":"regions","label":"Replica regions (comma-separated)","required":True,"default":"us-east-1,eu-west-1"}]),
}


# ============================================================================
# Lambda
# ============================================================================
_LAMBDA = {
    "dashboard": analytics(
        "Lambda Dashboard", "dashboard",
        "Account-wide Lambda function metrics and recent activity.",
        [["metric","Metric"],["value","Value"]],
        derived_from="lambda:dashboard",
        sparklines=[["Invocations (24h)",100,5000,""],
                    ["Errors (24h)",0,50,""],
                    ["Avg duration (ms)",10,500,""]]),
    "applications": crud(
        "Applications", "apps",
        "Applications group related Lambda functions and AWS resources.",
        [["name","Application"],["description","Description"],
         ["function_count","Functions"],["last_deployed","Last deployed"],["status","Status"]],
        [{"name":"name","label":"Application name","required":True},
         {"name":"description","label":"Description"}]),
    "layers": crud(
        "Layers", "layers",
        "Shared libraries and runtime dependencies you can attach to multiple Lambda functions.",
        [["name","Name"],["version","Latest version"],
         ["compatible_runtimes","Compatible runtimes"],["created","Created"]],
        [{"name":"name","label":"Layer name","required":True},
         {"name":"compatible_runtimes","label":"Compatible runtimes (comma-separated)",
          "default":"python3.12,python3.11"},
         {"name":"description","label":"Description"}]),
    "code-signing": crud(
        "Code signing", "verified",
        "Code-signing configurations to verify function code authenticity.",
        [["arn","Configuration ARN"],["description","Description"],
         ["signing_profile","Signing profile"],["created","Created"]],
        [{"name":"description","label":"Description","required":True},
         {"name":"signing_profile","label":"AWS Signer profile ARN","required":True}]),
}


# ============================================================================
# API Gateway
# ============================================================================
_APIGW = {
    "domains": crud(
        "Custom domain names", "language",
        "Custom domain names that you map to your APIs.",
        [["domain","Domain name"],["api_mappings","API mappings"],
         ["certificate_arn","Certificate ARN"],["endpoint_type","Endpoint type"],["status","Status"]],
        [{"name":"domain","label":"Domain name","required":True,
          "validate":{"regex":r"^[a-z0-9.-]+\.[a-z]{2,}$","message":"valid domain (e.g. api.example.com)"}},
         {"name":"certificate_arn","label":"ACM certificate ARN","required":True,
          "default":"arn:aws:acm:us-east-1:123456789012:certificate/xxxxxxxx"},
         {"name":"endpoint_type","label":"Endpoint type","type":"select","default":"REGIONAL",
          "options":[{"value":"REGIONAL","label":"Regional"},
                     {"value":"EDGE","label":"Edge-optimized"}]}]),
    "vpc-links": crud(
        "VPC links", "lan",
        "VPC links connect API Gateway to private resources inside your VPC.",
        [["id","ID"],["name","Name"],["target_arns","Target ARNs"],
         ["status","Status"],["created","Created"]],
        [{"name":"name","label":"VPC link name","required":True},
         {"name":"target_arns","label":"Target NLB ARNs","required":True,
          "default":"arn:aws:elasticloadbalancing:us-east-1:..."}]),
    "client-certs": crud(
        "Client certificates", "verified",
        "Client SSL certificates that API Gateway presents to backends.",
        [["id","Certificate ID"],["description","Description"],
         ["created","Created"],["expires","Expires"]],
        [{"name":"description","label":"Description","required":True}]),
    "usage-plans": crud(
        "Usage plans", "trending_up",
        "Quota and throttle limits applied to API keys.",
        [["name","Name"],["throttle_rate","Rate (req/sec)"],
         ["throttle_burst","Burst"],["quota_limit","Quota"],["quota_period","Period"]],
        [{"name":"name","label":"Plan name","required":True},
         {"name":"throttle_rate","label":"Rate (req/sec)","type":"number","default":100,"validate":{"min":1,"max":10000}},
         {"name":"throttle_burst","label":"Burst capacity","type":"number","default":200,"validate":{"min":1,"max":20000}},
         {"name":"quota_limit","label":"Quota (requests)","type":"number","default":10000,"validate":{"min":1}},
         {"name":"quota_period","label":"Quota period","type":"select","default":"MONTH",
          "options":[{"value":"DAY","label":"DAY"},{"value":"WEEK","label":"WEEK"},{"value":"MONTH","label":"MONTH"}]}],
        seed=[{"name":"basic","throttle_rate":100,"throttle_burst":200,"quota_limit":10000,"quota_period":"MONTH"}]),
    "api-keys": crud(
        "API keys", "vpn_key",
        "API keys for authenticated access to your APIs.",
        [["name","Name"],["key_id","ID"],["enabled","Enabled"],["created","Created"]],
        [{"name":"name","label":"Key name","required":True},
         {"name":"enabled","label":"Enabled","type":"boolean","default":True}],
        seed=[{"name":"dev-key","key_id":"abc123def456","enabled":True,"created":_TIME}]),
}


# ============================================================================
# SQS
# ============================================================================
_SQS = {
    "dlqs": analytics(
        "Dead-letter queues", "warning",
        "Queues configured to receive messages that can't be processed by their source queues. Derived from queue redrive policies.",
        [["name","Queue name"],["arn","ARN"],["source_queues","Source queues"],["approximate_messages","Messages"]],
        derived_from="sqs:dlqs"),
}


# ============================================================================
# VPC
# ============================================================================
_VPC = {
    "dashboard": analytics(
        "VPC Dashboard", "dashboard",
        "Account-wide VPC resource summary.",
        [["metric","Metric"],["value","Value"]],
        derived_from="vpc:dashboard",
        sparklines=[["VPCs",1,10,""],
                    ["Subnets",2,30,""],
                    ["Security groups",5,50,""]]),
    "nat-gateways": crud(
        "NAT gateways", "swap_horiz",
        "NAT gateways enable instances in private subnets to reach the internet for outbound traffic.",
        [["id","NAT ID"],["state","State"],["vpc_id","VPC"],
         ["subnet_id","Subnet"],["elastic_ip","Elastic IP"],["type","Type"]],
        [{"name":"subnet_id","label":"Subnet","required":True},
         {"name":"type","label":"Type","type":"select","default":"public",
          "options":[{"value":"public","label":"Public"},{"value":"private","label":"Private"}]}]),
    "egress-only-igw": crud(
        "Egress-only IGWs", "logout",
        "IPv6-only egress gateways for outbound traffic from private subnets.",
        [["id","ID"],["state","State"],["vpc_id","VPC"]],
        [{"name":"vpc_id","label":"VPC","required":True}]),
    "carrier-gw": crud(
        "Carrier gateways", "network_node",
        "Carrier gateways route traffic between an AWS Wavelength Zone VPC and a telecom provider.",
        [["id","ID"],["state","State"],["vpc_id","VPC"]],
        [{"name":"vpc_id","label":"VPC","required":True}]),
    "dhcp-options": crud(
        "DHCP option sets", "dns",
        "DHCP option sets allow you to customize options like DNS and NTP servers passed to instances.",
        [["id","ID"],["owner","Owner"],["options","Options"],["vpcs","VPCs using"]],
        [{"name":"domain_name","label":"Domain name","default":"ec2.internal"},
         {"name":"domain_name_servers","label":"Domain name servers","default":"AmazonProvidedDNS"}],
        seed=[{"id":"dopt-default","owner":"123456789012",
               "options":"domain-name: ec2.internal, domain-name-servers: AmazonProvidedDNS","vpcs":"vpc-default"}]),
    "elastic-ips": crud(
        "Elastic IPs", "public",
        "Static public IPv4 addresses available for use in this VPC.",
        [["allocation_id","Allocation ID"],["public_ip","Public IPv4"],
         ["associated_with","Associated with"],["scope","Scope"]],
        [{"name":"description","label":"Tag: Name","default":"vpc-eip"}]),
    "endpoints": crud(
        "Endpoints", "hub",
        "VPC endpoints allow private connectivity to AWS services without traversing the internet.",
        [["id","Endpoint ID"],["vpc_id","VPC"],["service_name","Service"],
         ["type","Type"],["state","State"]],
        [{"name":"vpc_id","label":"VPC","required":True,"default":"vpc-default"},
         {"name":"service_name","label":"Service","required":True,"default":"com.amazonaws.us-east-1.s3"},
         {"name":"type","label":"Type","type":"select","default":"Gateway",
          "options":[{"value":"Gateway","label":"Gateway"},
                     {"value":"Interface","label":"Interface"},
                     {"value":"GatewayLoadBalancer","label":"Gateway Load Balancer"}]}]),
    "endpoint-services": crud(
        "Endpoint services", "settings_ethernet",
        "Your own services that other AWS accounts can connect to via interface endpoints.",
        [["id","Service ID"],["owner","Owner"],["state","State"],["availability_zones","AZs"]],
        [{"name":"network_load_balancer_arns","label":"NLB ARNs","required":True}]),
    "peering": crud(
        "Peering connections", "compare_arrows",
        "VPC peering connections between two VPCs in the same or different accounts/regions.",
        [["id","Connection ID"],["requester_vpc","Requester VPC"],
         ["accepter_vpc","Accepter VPC"],["status","Status"]],
        [{"name":"requester_vpc","label":"Requester VPC","required":True,"default":"vpc-default"},
         {"name":"accepter_vpc","label":"Accepter VPC","required":True}]),
    "nacls": crud(
        "Network ACLs", "verified_user",
        "Stateless subnet-level firewall rules. Default NACL allows all traffic.",
        [["id","ACL ID"],["vpc_id","VPC"],["associated_subnets","Associated subnets"],
         ["inbound_rules","Inbound rules"],["outbound_rules","Outbound rules"]],
        [{"name":"vpc_id","label":"VPC","required":True,"default":"vpc-default"}],
        seed=[{"id":"acl-default","vpc_id":"vpc-default","associated_subnets":"all",
               "inbound_rules":"1 rule (allow all)","outbound_rules":"1 rule (allow all)"}]),
    "reachability": crud(
        "Reachability Analyzer", "find_in_page",
        "Network analyses that verify whether traffic between two endpoints can be delivered.",
        [["analysis_id","Analysis ID"],["source","Source"],["destination","Destination"],
         ["result","Result"],["created","Created"]],
        [{"name":"source","label":"Source resource ID","required":True,"default":"i-0abc1234"},
         {"name":"destination","label":"Destination resource ID","required":True,"default":"i-0def5678"}]),
}


# ============================================================================
# EventBridge — primary "rules" + 8 sub-features
# ============================================================================
_EVENTBRIDGE = {
    "rules": crud(
        "Rules", "rule",
        "Rules match incoming events and route them to one or more targets.",
        [["name","Name"],["event_bus_name","Event bus"],["rule_type","Type"],
         ["state","Status"],["target_count","Targets"]],
        [{"name":"name","label":"Rule name","required":True},
         {"name":"event_bus_name","label":"Event bus","default":"default"},
         {"name":"rule_type","label":"Rule type","type":"select","default":"EventPattern",
          "options":[{"value":"EventPattern","label":"Rule with an event pattern"},
                     {"value":"Schedule","label":"Schedule"}]}],
        seed=[
            {"name":"ec2-state-changes","event_bus_name":"default","rule_type":"EventPattern",
             "state":"ENABLED","target_count":1},
            {"name":"daily-cleanup","event_bus_name":"default","rule_type":"Schedule",
             "state":"ENABLED","target_count":1},
        ]),
    "event-buses": crud(
        "Event buses", "hub",
        "Event buses receive events from AWS services, partners, and your own applications.",
        [["name","Name"],["type","Type"],["rules_count","Rules"],["created","Created"]],
        [{"name":"name","label":"Bus name","required":True}],
        seed=[
            {"name":"default","type":"AWS","rules_count":2,"created":_TIME},
            {"name":"custom-app-bus","type":"Custom","rules_count":0,"created":_TIME},
        ]),
    "archives": crud(
        "Archives", "inventory",
        "Capture events from an event bus for retention or replay.",
        [["name","Name"],["event_source","Event source"],["state","State"],
         ["event_count","Events stored"],["size_mb","Size (MB)"]],
        [{"name":"name","label":"Archive name","required":True},
         {"name":"event_source","label":"Event source ARN","required":True},
         {"name":"retention_days","label":"Retention (days)","type":"number","default":7}]),
    "replays": crud(
        "Replays", "replay",
        "Re-process archived events through your rules and targets.",
        [["name","Name"],["archive","Archive"],["state","State"],
         ["progress","Progress"],["started","Started"]],
        [{"name":"name","label":"Replay name","required":True},
         {"name":"archive","label":"Archive","required":True}]),
    "connections": crud(
        "Connections", "link",
        "OAuth or API key credentials for API destination targets.",
        [["name","Name"],["auth_type","Auth type"],["state","State"]],
        [{"name":"name","label":"Connection name","required":True},
         {"name":"auth_type","label":"Auth type","type":"select","default":"API_KEY",
          "options":[{"value":"API_KEY","label":"API Key"},
                     {"value":"BASIC","label":"Basic"},
                     {"value":"OAUTH_CLIENT_CREDENTIALS","label":"OAuth Client Credentials"}]}]),
    "api-destinations": crud(
        "API destinations", "outbound",
        "HTTPS endpoints to invoke when a rule matches.",
        [["name","Name"],["invocation_endpoint","Endpoint"],["http_method","HTTP method"],
         ["state","State"]],
        [{"name":"name","label":"Destination name","required":True},
         {"name":"invocation_endpoint","label":"Endpoint URL","required":True,
          "default":"https://example.com/webhook"},
         {"name":"http_method","label":"HTTP method","type":"select","default":"POST",
          "options":[{"value":"POST","label":"POST"},{"value":"PUT","label":"PUT"},
                     {"value":"PATCH","label":"PATCH"},{"value":"DELETE","label":"DELETE"}]}]),
    "endpoints": crud(
        "Global endpoints", "public",
        "Failover-routing endpoints for cross-Region disaster recovery.",
        [["name","Name"],["primary_bus","Primary"],["secondary_bus","Secondary"],["state","State"]],
        [{"name":"name","label":"Endpoint name","required":True}]),
    "pipes": crud(
        "Pipes", "swap_horiz",
        "Point-to-point integrations from a source (SQS, Kinesis) to a target (Lambda, Step Functions).",
        [["name","Name"],["source","Source"],["target","Target"],
         ["state","State"]],
        [{"name":"name","label":"Pipe name","required":True}]),
    "schema-registries": crud(
        "Schema registries", "schema",
        "Discover, manage, and version schemas for events on your event buses.",
        [["name","Name"],["description","Description"],["schema_count","Schemas"]],
        [{"name":"name","label":"Registry name","required":True}],
        seed=[{"name":"discovered-schemas","description":"Auto-discovered from event bus traffic","schema_count":"15"}]),
}


# ============================================================================
# Secrets Manager — primary "secrets" + sub-features
# ============================================================================
_SECRETSMANAGER = {
    "secrets": crud(
        "Secrets", "key",
        "Encrypted secret values (DB credentials, API keys, OAuth tokens). KMS-encrypted at rest.",
        [["name","Secret name"],["secret_type","Type"],
         ["created","Created"],
         ["kms_key_id","Encryption key"]],
        [{"name":"name","label":"Secret name","required":True},
         {"name":"secret_type","label":"Type","type":"select","default":"Other",
          "options":[{"value":"RdsCredentials","label":"RDS credentials"},
                     {"value":"OtherDb","label":"Other database"},
                     {"value":"Other","label":"Other (API keys, etc.)"}]}],
        seed=[
            {"name":"prod/db/postgres","secret_type":"RdsCredentials",
             "created":_TIME,
             "kms_key_id":"aws/secretsmanager"},
            {"name":"prod/api/stripe","secret_type":"Other",
             "created":_TIME,
             "kms_key_id":"aws/secretsmanager"},
        ]),
    "rotation": analytics(
        "Rotation", "autorenew",
        "Schedule and history of secret-rotation Lambda invocations.",
        [["secret","Secret"],["status","Status"],["last_run","Last run"],
         ["next_run","Next run"],["lambda_arn","Rotation Lambda"]],
        seed=[
            {"secret":"prod/db/postgres","status":"Succeeded","last_run":_TIME,
             "next_run":"2026-06-28T00:00:00Z","lambda_arn":"arn:aws:lambda:us-east-1:123456789012:function:rotate-rds"},
        ]),
    "replicas": crud(
        "Replication", "public",
        "Secrets replicated to additional AWS Regions for HA.",
        [["primary_secret","Primary"],["region","Region"],["kms_key_id","Encryption key"],
         ["status","Status"]],
        [{"name":"primary_secret","label":"Primary secret","required":True},
         {"name":"region","label":"Replica Region","required":True,"default":"us-west-2"}]),
    "rotation-functions": crud(
        "Rotation functions", "bolt",
        "Lambda functions that perform the rotation logic.",
        [["name","Function name"],["runtime","Runtime"],["secret_types","Supports"]],
        [{"name":"name","label":"Function name","required":True}]),
}


# ============================================================================
# KMS — primary "keys" + sub-features
# ============================================================================
_KMS = {
    "keys": crud(
        "Customer managed keys", "key",
        "Keys you create and manage. Use for encrypt/decrypt/sign/verify and KMS-integrated AWS services.",
        [["key_id","Key ID"],["alias","Alias"],["key_spec","Type"],
         ["key_usage","Usage"],["state","Status"],["created","Created"]],
        [{"name":"name","label":"Alias","required":True},
         {"name":"key_spec","label":"Key spec","type":"select","default":"SYMMETRIC_DEFAULT",
          "options":[{"value":"SYMMETRIC_DEFAULT","label":"Symmetric"},
                     {"value":"RSA_2048","label":"RSA 2048"},
                     {"value":"RSA_4096","label":"RSA 4096"},
                     {"value":"ECC_NIST_P256","label":"ECC NIST P-256"},
                     {"value":"HMAC_256","label":"HMAC 256"}]},
         {"name":"key_usage","label":"Usage","type":"select","default":"ENCRYPT_DECRYPT",
          "options":[{"value":"ENCRYPT_DECRYPT","label":"Encrypt/Decrypt"},
                     {"value":"SIGN_VERIFY","label":"Sign/Verify"},
                     {"value":"GENERATE_VERIFY_MAC","label":"Generate/Verify MAC"}]}],
        seed=[
            {"key_id":"1234abcd-12ab-34cd-56ef-1234567890ab","alias":"alias/my-app-key",
             "key_spec":"SYMMETRIC_DEFAULT","key_usage":"ENCRYPT_DECRYPT",
             "state":"Enabled","created":_TIME},
            {"key_id":"5678efgh-12ab-34cd-56ef-1234567890ab","alias":"alias/db-encryption",
             "key_spec":"SYMMETRIC_DEFAULT","key_usage":"ENCRYPT_DECRYPT",
             "state":"Enabled","created":_TIME},
        ]),
    "aws-managed-keys": analytics(
        "AWS managed keys", "verified",
        "KMS keys created and managed by AWS services on your behalf (cannot be deleted).",
        [["key_id","Key ID"],["alias","Alias"],["service","Used by service"]],
        seed=[
            {"key_id":"aws/ebs","alias":"aws/ebs","service":"Amazon EBS"},
            {"key_id":"aws/s3","alias":"aws/s3","service":"Amazon S3"},
            {"key_id":"aws/rds","alias":"aws/rds","service":"Amazon RDS"},
            {"key_id":"aws/secretsmanager","alias":"aws/secretsmanager","service":"Secrets Manager"},
            {"key_id":"aws/lambda","alias":"aws/lambda","service":"AWS Lambda"},
        ]),
    "aliases": crud(
        "Aliases", "label",
        "Friendly names for KMS keys. Aliases can be re-pointed without changing apps.",
        [["alias_name","Alias"],["key_id","Target key"],["target_alias","Target alias"]],
        [{"name":"name","label":"Alias name (must start with 'alias/')","required":True,
          "default":"alias/my-alias"},
         {"name":"key_id","label":"Target key ID","required":True}]),
    "custom-key-stores": crud(
        "Custom key stores", "vpn_lock",
        "AWS CloudHSM-backed key stores for FIPS 140-2 Level 3 keys.",
        [["name","Name"],["type","Type"],["state","State"],["associated_cluster","CloudHSM cluster"]],
        [{"name":"name","label":"Store name","required":True}]),
    "audit-events": analytics(
        "AWS Config events", "fact_check",
        "Recent KMS key configuration changes tracked by AWS Config.",
        [["event_id","Event ID"],["resource","Resource"],["action","Action"],
         ["compliance","Compliance"],["recorded_at","Recorded"]],
        seed=[
            {"event_id":"ce-001","resource":"alias/my-app-key","action":"KeyRotated",
             "compliance":"COMPLIANT","recorded_at":_TIME},
        ]),
}


# ============================================================================
# Combined registry — keyed by "<service>/<stub-key>"
# ============================================================================
def _flatten(svc_dict, svc):
    return {f"{svc}/{k}": v for k, v in svc_dict.items()}


EXTRAS: dict[str, dict] = {
    **_flatten(_EC2, "ec2"),
    **_flatten(_S3, "s3"),
    **_flatten(_IAM, "iam"),
    **_flatten(_RDS, "rds"),
    **_flatten(_DYNAMO, "dynamodb"),
    **_flatten(_LAMBDA, "lambda"),
    **_flatten(_APIGW, "apigateway"),
    **_flatten(_SQS, "sqs"),
    **_flatten(_VPC, "vpc"),
    **_flatten(_EVENTBRIDGE, "eventbridge"),
    **_flatten(_SECRETSMANAGER, "secretsmanager"),
    **_flatten(_KMS, "kms"),
}
