"""NoSqlStore — the data-plane seam for DynamoDB (ADR-001).

The DynamoDB protocol logic (typed attribute values, key schema, item CRUD,
Query/Scan, native JSON errors) is substrate-independent and lives in
core/dynamodb_core.py. THIS is the seam it persists through, so the same handler
runs on any substrate:

    Pro/Max : DynamoDbLocalBackedStore — appliance ctx dict + optional mirror
    Nano    : InMemoryNoSqlStore — pure in-WASM (Pyodide); PGlite/IDB later
    tests   : InMemoryNoSqlStore

The store owns the one state dict the handler reads/writes — exactly the
`tables` map the original `ddb_state` route used — plus mirror/persist/cap hooks
that default to no-ops. Nothing here imports fastapi / boto3 / socket, so it
loads under Pyodide.

State shapes (unchanged from providers/aws_services.py's ddb_state["tables"]):
    tables : { name -> table }
    table  : { table_name, table_arn, table_status, partition_key_name,
               partition_key_type, sort_key_name, sort_key_type, billing_mode,
               provisioned_throughput, tags, indexes, streams, key_schema,
               attribute_definitions, created, last_modified, item_count,
               table_size_bytes, items: { key_string -> record } }
    record : { item: {attr -> native}, created, updated, size_bytes }
    key_string = json.dumps([pk_value, sk_value|None], separators=(",",":"))
    backups : { arn -> backup }  (on-demand snapshots; see dynamodb_core CreateBackup)
    backup  : { backup_arn, backup_name, table_name, table_arn, backup_status,
                backup_type, backup_size_bytes, backup_creation_datetime,
                source_table: <deep copy of table, including items, at snapshot time> }
    exports : { arn -> export }  (ExportTableToPointInTime job records; the bytes
                themselves land in the S3 store, not here)
    imports : { arn -> import }  (ImportTable job records; the source bytes are read
                from the S3 store, not here)
"""
from __future__ import annotations

from typing import Any

DEFAULT_ACCOUNT_ID = "123456789012"  # matches core.app_context.AWS_ACCOUNT_ID


class NoSqlStore:
    """Base seam. In-memory by default; subclass to add a mirror / persistence."""

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID) -> None:
        self.tables: dict[str, dict[str, Any]] = {}
        self.backups: dict[str, dict[str, Any]] = {}
        self.exports: dict[str, dict[str, Any]] = {}
        self.imports: dict[str, dict[str, Any]] = {}
        self.account_id = account_id

    # ── table map accessors (the {name -> table} dict) ────────────────
    def table_exists(self, name: str) -> bool:
        return name in self.tables

    def get_table(self, name: str) -> dict | None:
        t = self.tables.get(name)
        return t if isinstance(t, dict) else None

    def put_table(self, name: str, table: dict) -> None:
        self.tables[name] = table

    def drop_table(self, name: str) -> None:
        self.tables.pop(name, None)

    def table_names(self) -> list[str]:
        return sorted(self.tables)

    # ── backup map accessors (the {arn -> backup} dict) ────────────────
    def get_backup(self, arn: str) -> dict | None:
        b = self.backups.get(arn)
        return b if isinstance(b, dict) else None

    def put_backup(self, arn: str, backup: dict) -> None:
        self.backups[arn] = backup

    def drop_backup(self, arn: str) -> None:
        self.backups.pop(arn, None)

    def list_backups(self) -> list[dict]:
        return list(self.backups.values())

    # ── export map accessors (the {arn -> export} dict; ExportTableToPointInTime) ──
    def get_export(self, arn: str) -> dict | None:
        e = self.exports.get(arn)
        return e if isinstance(e, dict) else None

    def put_export(self, arn: str, export: dict) -> None:
        self.exports[arn] = export

    def list_exports(self) -> list[dict]:
        return list(self.exports.values())

    # ── import map accessors (the {arn -> import} dict; ImportTable) ───────
    def get_import(self, arn: str) -> dict | None:
        i = self.imports.get(arn)
        return i if isinstance(i, dict) else None

    def put_import(self, arn: str, imp: dict) -> None:
        self.imports[arn] = imp

    def list_imports(self) -> list[dict]:
        return list(self.imports.values())

    # ── optional hooks (no-ops in the base) ───────────────────────────
    def persist(self) -> None:
        """Flush state to durable storage (appliance ctx in Pro/Max, IDB/OPFS in
        Nano later). The in-memory dict is the source of truth either way."""

    def mirror_create_table(self, name: str, table: dict) -> None:
        """Best-effort create in an external backend (DynamoDB-Local in Pro/Max)."""

    def mirror_delete_table(self, name: str) -> None:
        """Best-effort delete-table in the external mirror."""

    def mirror_put_item(self, table_name: str, key: str, item: dict) -> None:
        """Best-effort item write-through to the external mirror."""

    def mirror_delete_item(self, table_name: str, key: str) -> None:
        """Best-effort item delete in the external mirror."""

    def enforce_storage_cap(self, additional_bytes: int) -> None:
        """Tier storage-quota gate (Pro/Max wires this to server.py). No-op in
        Nano/tests — the WASM tab has no tier server to consult."""


class InMemoryNoSqlStore(NoSqlStore):
    """The Nano / test substrate: pure in-memory, zero external deps. Identical
    to the appliance's in-memory behavior minus the DynamoDB-Local mirror."""
