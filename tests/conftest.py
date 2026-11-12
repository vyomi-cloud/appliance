"""Test-wide defaults.

The appliance coalesces state saves (core/middleware._schedule_persist: one flush per burst
of mutating requests, VYOMI_PERSIST_DEBOUNCE_MS, default 250 ms). Durability tests read the
state store right after a request, so the suite runs with per-request saves; the coalescing
itself is covered by tests/test_persist_coalescing.py.
"""
import os

os.environ.setdefault("VYOMI_PERSIST_DEBOUNCE_MS", "0")
