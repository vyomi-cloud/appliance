# Console actions — conformance suite

Permanent CI-runnable test harness that exercises **every CRUD + lifecycle
action** advertised by the AWS / GCP / Azure console catalogs.

## Why this exists

The console catalogs (`providers/{aws,gcp,azure}_catalog.py`,
`providers/azure_services.py:RESOURCE_CATALOG`) are the contract between
each cloud's UI and its backend. When that contract drifts — wrong
endpoint, wrong method, missing handler — the user sees buttons that
silently do nothing. This suite walks the catalogs end-to-end against a
live appliance and FAILS the build the moment any contract breaks.

## What it tests

For every service in every catalog:

| Operation | Endpoint exercised |
|---|---|
| **list**     | `GET collection_path` |
| **create**   | `POST/PUT collection_path` (payloads in `sample_payloads.py`) |
| **get**      | `GET resource_path` with the created id |
| **update**   | `PATCH/PUT resource_path` (if defined in `api_paths`) |
| **lifecycle**| start, stop, reboot, restart (any service-defined verb) |
| **delete**   | `DELETE resource_path` (or `POST .../terminate`) |

Tests are **parameterized from the running simulator's
`/api/{cloud}/catalog`** — no manual mapping. Add a service to the
catalog, you automatically add tests.

## Pass-rate gate

The CI workflow at `.github/workflows/console-conformance.yml` fails
the build if pass-rate < **100%** for any provider. Tier-gated services
that legitimately return 403 are marked `skipped`, not `failed`, so
the gate works at any appliance tier.

## Run locally

You'll need a running appliance at `http://127.0.0.1:9000` (or set
`VYOMI_BASE_URL`):

```bash
# Start your appliance first
cloud-learn appliance up

# Then run the suite
cd cloud-learn
VYOMI_BASE_URL=http://127.0.0.1:9000 \
  python3 -m pytest tests/conformance/console_actions/ -v
```

For the live appliance running in multipass, point at its IP:

```bash
VYOMI_BASE_URL=http://192.168.252.7:9000 \
  python3 -m pytest tests/conformance/console_actions/ -v
```

Reports land at `tests/conformance/console_actions/REPORT.md`.

## CI usage

```yaml
- name: Boot appliance compose stack
  run: docker compose -f docker-compose.appliance.yml up -d simulator
- name: Wait for /healthz
  run: until curl -fs http://localhost:9000/healthz; do sleep 2; done
- name: Run console conformance
  env:
    VYOMI_BASE_URL: http://localhost:9000
    VYOMI_TIER: developer   # all-clouds tier
  run: python3 -m pytest tests/conformance/console_actions/ --junitxml=results.xml
- name: Fail if pass-rate < 100
  run: ./tests/conformance/console_actions/check_pass_rate.sh
```

## Adding a new service

1. Add the entry to the catalog file.
2. Add a minimal `payload_for(...)` entry to `sample_payloads.py`.
3. CI runs automatically include the new tests.

## When a test fails

Read `REPORT.md` — the failure row shows the path, method, status code,
and the first 80 chars of the response body. Common causes:

- **404 NoSuchBucket XML** → wrong HTTP method or wrong path; the S3
  catch-all swallows it. Check `routes/aws_s3.py` registration order.
- **404 not found**           → endpoint just doesn't exist; add the
                                handler in `server.py` or `providers/`.
- **400 invalid_request**     → payload doesn't match the schema; fix
                                `sample_payloads.py`.
- **403 tier_provider_locked**→ legitimate tier gate; harness should
                                already skip these (check `_TIER_GATED`
                                in `conftest.py`).
- **500**                     → real backend bug; check simulator logs.
