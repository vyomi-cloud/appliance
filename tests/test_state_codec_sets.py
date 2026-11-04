"""The offline state is persisted as JSON: sets (e.g. Microsoft Graph group memberships,
core/azure_graph_core.GraphStore.group_members) must round-trip as sets — before this, one
group member made EVERY later state save fail ("Object of type set is not JSON serializable")."""
import json

from core.vyomi_platform import _decode_state_value, _encode_state_value


def test_sets_round_trip_through_the_json_state_codec():
    state = {"azure_graph": {"group_members": {"g1": {"u1", "u2"}, "g2": set()}},
             "blob": b"\x00\x01", "nested": [1, {"x"}]}
    back = _decode_state_value(json.loads(json.dumps(_encode_state_value(state))))
    assert back == state
    assert isinstance(back["azure_graph"]["group_members"]["g1"], set)


def test_sets_round_trip_through_nanos_persistence_codec():
    """Nano's snapshot codec silently skipped any store field holding a set (it failed the
    JSON probe), so Graph group memberships were never persisted in the browser."""
    from core.nano_persist import _dec, _enc
    v = {"group_members": {"g1": {"u1", "u2"}}, "raw": b"\x01"}
    assert _dec(json.loads(json.dumps(_enc(v)))) == v
