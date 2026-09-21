"""tests/test_collective_payload_contract.py — P1B.1: payload units.

`bytes_per_element` is an opaque historical scalar (no computational
consumer exists); `payload_bytes` is the explicit lowering authority.
Old documents must serialize and hash exactly as before.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from veritx_dse.model.compile_model import (  # noqa: E402
    CollectiveOp, CollectiveKind, CompileRequest,
)


class TestPayloadContract:
    def test_old_shape_serializes_without_payload_bytes(self):
        c = CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8,
                         bytes_per_element=2048)
        assert c.to_dict() == {"kind": "allreduce", "group_size": 8,
                               "bytes_per_element": 2048}
        assert c.payload_bytes is None

    def test_old_document_parses_with_undeclared_payload(self):
        c = CollectiveOp.from_dict({"kind": "allreduce", "group_size": 8,
                                    "bytes_per_element": 2048})
        assert c.payload_bytes is None
        assert c.to_dict() == {"kind": "allreduce", "group_size": 8,
                               "bytes_per_element": 2048}

    def test_payload_bytes_round_trips(self):
        c = CollectiveOp.from_dict(
            {"kind": "allgather", "group_size": 8,
             "bytes_per_element": 2048, "payload_bytes": 65536})
        assert c.payload_bytes == 65536
        assert CollectiveOp.from_dict(c.to_dict()) == c

    def test_payload_bytes_moves_identity(self):
        a = CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8)
        b = CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8,
                         payload_bytes=2048)
        assert a.to_dict() != b.to_dict()

    @pytest.mark.parametrize("bad", [0, -1, 1.5, "2048", True, [2048]])
    def test_bad_payload_bytes_refuses(self, bad):
        with pytest.raises(Exception):
            CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8,
                         payload_bytes=bad)

    def test_p1a_example_hash_unmoved_by_new_field(self):
        """The P1A slice example declares no payload_bytes: its design
        identity must equal the value the sealed P1A tree computed
        (verified identical with and without this change)."""
        doc = json.loads((DSE.parent / "examples"
                          / "llama_dense_64tiles.json").read_text())
        req = CompileRequest.from_dict(doc)
        assert req.design_hash() == (
            "47cefaa0d0527e8249b64b96b5e721c1052aef1788c653711222b670e4246d88")
        assert all("payload_bytes" not in c for c in
                   req.to_dict()["workload"]["collectives"])
