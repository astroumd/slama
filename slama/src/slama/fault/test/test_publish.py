"""Unit tests for slama.fault.publish (no SMAX required)."""
import json

import pytest

from slama.fault.faultnode import FaultNode
from slama.fault.publish import (
    FAULT_HEARTBEAT_NAME, SNAPSHOT_VERSION, STATE_NAME, build_snapshot, node_state,
    parse_snapshot, publish, state_counts,
)
from slama.monitor.monitorpoint import Validity


class TestNodeState:
    @pytest.mark.parametrize("sets, ignored, expected", [
        (dict(faulted=set(), debounced=set(), hidden=set()), False, "ok"),
        # hidden beats everything else, even debounced and ignored
        (dict(faulted={"x"}, debounced={"x"}, hidden={"x"}), True, "consequence"),
        (dict(faulted={"x"}, debounced=set(), hidden=set()), True, "debouncing"),
        (dict(faulted={"x"}, debounced={"x"}, hidden=set()), True, "ignored"),
        (dict(faulted={"x"}, debounced={"x"}, hidden=set()), False, "root"),
    ])
    def test_precedence(self, sets, ignored, expected):
        assert node_state("x", ignored=ignored, **sets) == expected


def _snapshot():
    nodes = {
        "monitorsystem:p": FaultNode("monitorsystem:p", faulted_since=100.0),
        "monitorsystem:c": FaultNode("monitorsystem:c", parents=["monitorsystem:p", "monitorsystem:q"],
                                     faulted_since=90.0),
        "monitorsystem:q": FaultNode("monitorsystem:q"),
    }
    return build_snapshot(
        nodes,
        validities={"monitorsystem:p": Validity.VALID_ERROR,
                    "monitorsystem:c": Validity.INVALID_NO_DATA,
                    "monitorsystem:q": Validity.VALID_GOOD},
        faulted={"monitorsystem:p", "monitorsystem:c"},
        debounced={"monitorsystem:p"}, hidden={"monitorsystem:c"},
        is_ignored=lambda name: False, tick=123.0, interval_s=2,
    )


class TestBuildSnapshot:
    def test_shape(self):
        assert _snapshot() == {
            "version": SNAPSHOT_VERSION, "tick": 123.0, "interval_s": 2.0,
            "nodes": {
                "monitorsystem:p": {"state": "root", "validity": "VALID_ERROR", "since": 100.0},
                "monitorsystem:c": {"state": "consequence", "validity": "INVALID_NO_DATA",
                                    "since": 90.0, "hidden_by": ["monitorsystem:p"]},
                "monitorsystem:q": {"state": "ok", "validity": "VALID_GOOD", "since": None},
            },
        }

    def test_counts(self):
        assert state_counts(_snapshot()) == {
            "ok": 1, "consequence": 1, "debouncing": 0, "ignored": 0, "root": 1}


class RecordingClient:
    def __init__(self):
        self.shares = []

    def smax_share(self, table, key, value):
        self.shares.append((f"{table}:{key}", value))


class TestPublishAndParse:
    def test_state_then_heartbeat(self):
        client = RecordingClient()
        publish(client, _snapshot())
        assert [name for name, _ in client.shares] == [STATE_NAME, FAULT_HEARTBEAT_NAME]
        assert isinstance(client.shares[0][1], str)
        assert client.shares[1][1] == 123.0

    def test_round_trip(self):
        client = RecordingClient()
        publish(client, _snapshot())
        assert parse_snapshot(client.shares[0][1]) == _snapshot()
        assert parse_snapshot(client.shares[0][1].encode()) == _snapshot()

    def test_compact_json(self):
        client = RecordingClient()
        publish(client, _snapshot())
        assert ", " not in client.shares[0][1] and ": " not in client.shares[0][1]

    @pytest.mark.parametrize("text", ["not json", "[1, 2]", json.dumps({"version": 2}),
                                      json.dumps({"nodes": {}})])
    def test_bad_snapshot_rejected(self, text):
        with pytest.raises(ValueError):
            parse_snapshot(text)
