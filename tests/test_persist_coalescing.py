"""A burst of mutating requests costs ONE state save, not one per request (the AWS JSON
protocol sends reads as POSTs: a console page firing 120 DescribeTable calls used to pay 120
full-state serializations in a row — the offline 'stall'). The save still happens."""
import asyncio

from core import middleware as mw


def test_burst_is_coalesced_into_one_save(monkeypatch):
    calls = []
    monkeypatch.setattr(mw, "_persist_state", lambda: calls.append(1))
    monkeypatch.setenv("VYOMI_PERSIST_DEBOUNCE_MS", "50")

    async def burst():
        for _ in range(120):
            mw._schedule_persist()
        assert calls == []                     # nothing written inline
        await asyncio.sleep(0.2)
    asyncio.run(burst())
    assert calls == [1]                        # exactly one save for the whole burst


def test_zero_debounce_saves_per_request(monkeypatch):
    calls = []
    monkeypatch.setattr(mw, "_persist_state", lambda: calls.append(1))
    monkeypatch.setenv("VYOMI_PERSIST_DEBOUNCE_MS", "0")
    for _ in range(3):
        mw._schedule_persist()
    assert calls == [1, 1, 1]


def test_shutdown_flushes_a_pending_save(monkeypatch):
    calls = []
    monkeypatch.setattr(mw, "_persist_state", lambda: calls.append(1))
    monkeypatch.setenv("VYOMI_PERSIST_DEBOUNCE_MS", "10000")

    async def pending_then_shutdown():
        mw._schedule_persist()
        await asyncio.sleep(0)
        mw.flush_pending_state()
    asyncio.run(pending_then_shutdown())
    assert calls == [1]
