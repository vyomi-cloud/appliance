"""NATS-backed messaging substrate (v2.4.0 Phase 4) — Pro/Max only.

The real-backend implementation of the MessagingStore seam: the SQS/SNS +
Pub/Sub cores keep their state (queues, topics, subscriptions, messages) in a
real NATS JetStream **KV bucket** instead of memory, so it's durable across a
fresh store instance — the same contract as the MinIO/Postgres/Vault substrates.

The cores call `store.persist()` after every mutation (the write-through hook);
we serialize the queue/topic dicts to the JetStream KV on persist() and load on
init. nats-py is async and the seam is sync, so a persistent asyncio loop runs
in a daemon thread and sync methods drive it via run_coroutine_threadsafe.

Imports nats-py + runs a network client → Pro/Max only, never vendored to WASM.
Nano uses the in-WASM InMemoryMessagingStore.
"""
from __future__ import annotations

import asyncio
import base64
import json
import threading

import nats

from core.messaging_store import InMemoryMessagingStore


def _enc(o):
    if isinstance(o, (bytes, bytearray)):
        return {"__b64__": base64.b64encode(bytes(o)).decode()}
    raise TypeError


def _hook(d):
    if len(d) == 1 and "__b64__" in d:
        return base64.b64decode(d["__b64__"])
    return d


class NatsBackedMessagingStore(InMemoryMessagingStore):
    _STATE = ("queues", "topics")

    def __init__(self, servers: str = "nats://localhost:4222",
                 bucket: str = "v24_messaging", store_id: str = "msg",
                 account_id: str | None = None):
        if account_id is None:
            super().__init__()
        else:
            super().__init__(account_id=account_id)
        self._sid = store_id
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._kv = self._run(self._connect(servers, bucket))
        self._load()

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=15)

    async def _connect(self, servers, bucket):
        self._nc = await nats.connect(servers)
        js = self._nc.jetstream()
        try:
            return await js.key_value(bucket)
        except Exception:
            return await js.create_key_value(bucket=bucket)

    def _load(self) -> None:
        async def _get():
            try:
                entry = await self._kv.get(self._sid)
                return entry.value
            except Exception:
                return None
        raw = self._run(_get())
        if raw:
            state = json.loads(raw.decode("utf-8"), object_hook=_hook)
            for attr in self._STATE:
                if attr in state:
                    setattr(self, attr, state[attr])

    def persist(self) -> None:
        blob = json.dumps({a: getattr(self, a) for a in self._STATE}, default=_enc).encode()
        self._run(self._kv.put(self._sid, blob))

    def close(self) -> None:
        try:
            self._run(self._nc.drain())
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
