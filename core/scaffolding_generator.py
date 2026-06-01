"""Tier-feature implementation: scaffolding_generator (Developer+ tiers).

Generates copy-pasteable starter code for AWS/GCP/Azure services across
three output formats:

  output=terraform      → HCL block (e.g. resource "aws_s3_bucket" "x" {...})
  output=cdk_python     → AWS CDK / pulumi-style Python snippet
  output=sdk_python     → boto3/google-cloud/azure-sdk client call

Endpoint: GET /api/scaffolding/generate?provider=aws&service=s3&output=terraform

Templates are inline (not heavy templating engine — pure f-string with
default parameter substitution). Adding a new (provider, service, output)
triple is a single new entry in `_TEMPLATES`.
"""
from __future__ import annotations

import re
from typing import Any


# Resource name → (resource_address, sane defaults) by (provider, service).
# Adding a new pair: just put one f-string per output format.
_TEMPLATES: dict[tuple[str, str], dict[str, str]] = {
    ("aws", "s3"): {
        "terraform": '''\
resource "aws_s3_bucket" "{name}" {{
  bucket = "{name}-${{random_id.suffix.hex}}"
}}

resource "aws_s3_bucket_versioning" "{name}" {{
  bucket = aws_s3_bucket.{name}.id
  versioning_configuration {{ status = "Enabled" }}
}}
''',
        "cdk_python": '''\
from aws_cdk import aws_s3 as s3, Stack
from constructs import Construct

class {name_camel}Stack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)
        bucket = s3.Bucket(self, "{name_camel}",
            versioned=True,
            removal_policy=RemovalPolicy.DESTROY,
        )
''',
        "sdk_python": '''\
import boto3
s3 = boto3.client("s3", endpoint_url="{endpoint}")
s3.create_bucket(Bucket="{name}")
s3.put_bucket_versioning(
    Bucket="{name}",
    VersioningConfiguration={{"Status": "Enabled"}},
)
''',
    },
    ("aws", "ec2"): {
        "terraform": '''\
resource "aws_instance" "{name}" {{
  ami           = "ami-amzn2023-x86_64"
  instance_type = "t3.micro"
  tags = {{
    Name = "{name}"
  }}
}}
''',
        "sdk_python": '''\
import boto3
ec2 = boto3.client("ec2", endpoint_url="{endpoint}")
resp = ec2.run_instances(
    ImageId="ami-amzn2023-x86_64",
    InstanceType="t3.micro",
    MinCount=1, MaxCount=1,
    TagSpecifications=[{{"ResourceType": "instance",
        "Tags": [{{"Key": "Name", "Value": "{name}"}}]}}],
)
print(resp["Instances"][0]["InstanceId"])
''',
    },
    ("aws", "lambda"): {
        "terraform": '''\
resource "aws_lambda_function" "{name}" {{
  function_name = "{name}"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "index.handler"
  runtime       = "python3.11"
  filename      = "function.zip"
}}
''',
        "sdk_python": '''\
import boto3
lam = boto3.client("lambda", endpoint_url="{endpoint}")
lam.create_function(
    FunctionName="{name}",
    Runtime="python3.11",
    Role="arn:aws:iam::000000000000:role/lambda-exec",
    Handler="index.handler",
    Code={{"ZipFile": open("function.zip", "rb").read()}},
)
''',
    },
    ("gcp", "storage"): {
        "terraform": '''\
resource "google_storage_bucket" "{name}" {{
  name     = "{name}-${{random_id.suffix.hex}}"
  location = "US"
  versioning {{ enabled = true }}
}}
''',
        "sdk_python": '''\
from google.cloud import storage
client = storage.Client(client_options={{"api_endpoint": "{endpoint}"}})
bucket = client.create_bucket("{name}")
bucket.versioning_enabled = True
bucket.patch()
''',
    },
    ("gcp", "compute"): {
        "terraform": '''\
resource "google_compute_instance" "{name}" {{
  name         = "{name}"
  machine_type = "e2-micro"
  zone         = "us-central1-a"
  boot_disk {{
    initialize_params {{ image = "debian-cloud/debian-12" }}
  }}
  network_interface {{
    network = "default"
    access_config {{}}
  }}
}}
''',
        "sdk_python": '''\
from google.cloud import compute_v1
client = compute_v1.InstancesClient(
    client_options={{"api_endpoint": "{endpoint}"}})
op = client.insert(
    project="my-project", zone="us-central1-a",
    instance_resource=compute_v1.Instance(
        name="{name}", machine_type="zones/us-central1-a/machineTypes/e2-micro",
    ),
)
op.result()
''',
    },
    ("azure", "storage"): {
        "terraform": '''\
resource "azurerm_storage_account" "{name}" {{
  name                     = "{name}sa"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}}
''',
        "sdk_python": '''\
from azure.storage.blob import BlobServiceClient
svc = BlobServiceClient(account_url="{endpoint}", credential="<key>")
svc.create_container("{name}")
''',
    },
    ("azure", "vm"): {
        "terraform": '''\
resource "azurerm_linux_virtual_machine" "{name}" {{
  name                = "{name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  size                = "Standard_B1s"
  admin_username      = "azureuser"
  network_interface_ids = [azurerm_network_interface.nic.id]
  os_disk {{
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }}
  source_image_reference {{
    publisher = "Canonical"
    offer     = "UbuntuServer"
    sku       = "22_04-lts"
    version   = "latest"
  }}
}}
''',
    },
}


_NAME_CAMEL_RE = re.compile(r"(^|[-_])(\w)")


def _camelize(name: str) -> str:
    return _NAME_CAMEL_RE.sub(lambda m: m.group(2).upper(), name)


def supported() -> list[dict]:
    """List all (provider, service, output) triples available."""
    out = []
    for (p, s), outputs in _TEMPLATES.items():
        for fmt in outputs:
            out.append({"provider": p, "service": s, "output": fmt})
    return sorted(out, key=lambda r: (r["provider"], r["service"], r["output"]))


def generate(provider: str, service: str, output: str,
             name: str = "my-resource", endpoint: str = "http://localhost:9000") -> dict:
    """Render a scaffolding snippet. Raises KeyError if the triple isn't
    supported (caller should 404)."""
    key = (provider.strip().lower(), service.strip().lower())
    if key not in _TEMPLATES:
        raise KeyError(f"unsupported provider/service: {provider}/{service}")
    fmt = output.strip().lower()
    if fmt not in _TEMPLATES[key]:
        raise KeyError(f"unsupported output {fmt!r} for {provider}/{service}")
    tmpl = _TEMPLATES[key][fmt]
    safe_name = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-") or "my-resource"
    snippet = tmpl.format(
        name=safe_name,
        name_camel=_camelize(safe_name),
        endpoint=endpoint,
    )
    return {
        "provider": provider, "service": service, "output": fmt,
        "name": safe_name, "endpoint": endpoint,
        "snippet": snippet,
        "lines": snippet.count("\n"),
    }
