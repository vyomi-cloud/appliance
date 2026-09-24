# Vyomi Cloud Sandbox

Run a faithful **multi-cloud simulator** — AWS, GCP, and Azure — entirely inside a **GitHub
Codespace**. No local install, no cloud account, no bill. Point your existing SDK/CLI code at it
and validate real application logic.

> _Build for the cloud, without the cloud._

## Pick a profile (turnkey)

When you **Create a Codespace**, GitHub shows a profile picker:

| Profile | Services |
|---------|----------|
| **All Clouds (full)** — default | AWS + GCP + Azure, everything + compute |
| **AWS (full)** | S3 · DynamoDB · SQS · SNS · IAM · KMS · Secrets Manager · RDS · EC2 |
| **GCP (full)** | Cloud Storage · Firestore · Pub/Sub · IAM · KMS · Secret Manager · Cloud SQL · Compute Engine |
| **Azure (full)** | Blob · Cosmos DB · Service Bus · Key Vault · RBAC · SQL Database · Virtual Machines |

Each profile boots only the backends it needs (Docker Compose profiles). Compute (EC2 / GCE / Azure
VM) launches as sibling Docker containers via the Codespace's docker-in-docker.

## Use it — smoke test

```bash
EP="$CLOUDLEARN_PUBLIC_URL"          # or http://localhost:9000 inside the Codespace

# AWS
aws --endpoint-url "$EP" s3 mb s3://demo && aws --endpoint-url "$EP" s3 ls
aws --endpoint-url "$EP" rds create-db-instance --db-instance-identifier demo-db \
  --engine postgres --db-instance-class db.t3.micro --allocated-storage 20 \
  --master-username admin --master-user-password secret99
aws --endpoint-url "$EP" ec2 run-instances --image-id ami-ubuntu --instance-type t3.micro

# GCP  (gcloud / google-cloud-* SDKs, endpoint = $EP)
# Azure (az / azure-sdk-*, endpoint = $EP)
```

`$CLOUDLEARN_PUBLIC_URL` is the forwarded `https://<codespace>-9000.app.github.dev` address
(external SDKs on your laptop can hit it too when the port is public). Inside the Codespace,
`http://localhost:9000` works directly.

## What's inside

| | |
|--|--|
| **Clouds** | AWS · GCP · Azure (pick one or all at create time) |
| **Compute** | Real instances (EC2 / GCE / VM) as sibling Docker containers |
| **Default tier** | Unlicensed = Free → 1 VM + 1 DB + 1 bucket per space (enough to smoke-test). Activate Pro for more. |
| **TTL** | 8 h by default — the sandbox stops itself after the window (`VYOMI_SANDBOX_TTL`) |
| **Cost** | $0 on your account's free Codespaces quota; metered in the Vyomi admin cost dashboard |

## Activate a paid tier (optional)

The console's **Activate** button runs the standard device flow (GitHub sign-in). Enterprises can
pre-seed a license via the `VYOMI_LICENSE_JWT` **Codespaces secret** — seats activate zero-click.

---

Profiles, compute size, and TTL are managed by your Vyomi enterprise admin. This template is
published from the appliance repo (`appliance/codespace/`); do not edit in place.
