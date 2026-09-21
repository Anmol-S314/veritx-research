"""tests/test_collective_payload_contract.py — P1B.1: payload units.

`bytes_per_element` is an opaque historical scalar (no computational
consumer exists); `payload_bytes` is the explicit lowering authority.
Old documents must serialize and hash exactly as before.
"""
from __future__ import annotations

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

    def test_old_shape_hash_unmoved_by_new_field(self):
        """A pre-P1B document (no payload_bytes anywhere) keeps its
        design identity under the new code: the optional field is
        omitted from serialization when undeclared. Hash verified
        identical on the sealed P1A tree and with this change."""
        doc = {
            "schema_version": 2, "compiler_semantics_version": 2,
            "workload": {
                "model_family": "dense_transformer", "tp": 2,
                "collectives": [{"kind": "allreduce", "group_size": 2,
                                 "bytes_per_element": 2048}],
            },
            "agents": [{"kind": "compute_tile", "count": 2}],
        }
        req = CompileRequest.from_dict(doc)
        assert req.design_hash() == (
            "da32daeae0187608e24fdb286d0294bb3ac3c7b49a9be9d43bbfbb41a566eed3")
        assert all("payload_bytes" not in c for c in
                   req.to_dict()["workload"]["collectives"])
