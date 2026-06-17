# UI Conformance — Playwright-driven SPA tests

**Purpose**: close the gap that lets bugs ship despite the SDK conformance
suite being 100 % green.

The existing conformance suites (`aws-sdk-go`, `aws-sdk-java`, `gcp-sdk-*`,
`terraform-gate`, `console_actions`) drive the simulator through **SDK
wire protocols** — boto3 PascalCase, aws-cli, Terraform, real
google-cloud-* clients. That's a useful slice but it misses one whole
surface: **the appliance's own React SPA**. The SPA sends payloads
using its own simplified field convention (`name` instead of
`db_instance_identifier`, `master_password` instead of
`master_user_password`, etc.).

A real example bug this suite catches: on 2026-06-17 the SPA's RDS
create form was sending `{name, master_password, instance_class}` —
none of which matched the Pydantic model — causing a 422 on every
single Create-DB click in the AWS console. The SDK suite passed
100 % because boto3 sends `{DBInstanceIdentifier, MasterUserPassword,
DBInstanceClass}` which the model DID accept.

## What this suite does

A small Playwright (Python) harness that:

1. Starts a headless Chromium pointed at `http://localhost:9000/ui`
2. For each service we ship in the AWS / GCP / Azure consoles:
   - Opens the console
   - Navigates to the service
   - Clicks **Create**
   - Fills the wizard with realistic values
   - Submits
   - Verifies the resource appears in the list
   - For data-plane services (RDS, S3, etc.), also asserts the
     underlying real backend reflects the create (psql connect,
     `mc ls`, etc.)

Tests live under `aws/`, `gcp/`, `azure/`. Shared helpers in
`_helpers.py`. Page-object stubs in `_pages/`.

## Running

```bash
# from appliance/ root:
.venv/bin/pytest tests/conformance/ui/ -v
```

Default endpoint is `http://localhost:9000`; override via the
`VYOMI_BASE_URL` env var. The simulator must already be running (the
suite doesn't try to spin it up — it assumes `vyomi up` has been
done).

Set `PWDEBUG=1` to run with the inspector visible:

```bash
PWDEBUG=1 .venv/bin/pytest tests/conformance/ui/aws/test_rds.py -v
```

## How to add a new test

1. Drop a `test_<service>.py` under `aws/`, `gcp/`, or `azure/`
2. Use the `appliance_page` fixture (provides a fresh browser context
   navigated to `/ui` with auth bypass cookies set)
3. Drive the SPA: `page.locator(...)` + Playwright's auto-waiting
4. For data-plane assertions, import `psycopg` or similar and connect
   to the appliance VM IP (`192.168.252.22` by default; see fixture
   `appliance_vm_ip`)

## What 100 % pass means

> Every wizard the appliance ships with successfully creates the
> resource via the exact payload the SPA actually sends, and the
> created resource is reachable on its native wire protocol.

That's a much stronger claim than the SDK-only conformance.
