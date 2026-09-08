"""Contract tests for the trace toolchain: model → trace → binary.

Covers the two previously-untested simulation modules:

- ``model_to_trace``: TrafficModel JSON → {cyc src cl dst sz} packets.
  Collective decomposition (ring allreduce/allgather/reduce-scatter, alltoall),
  participant filtering, cycle scheduling, and the CLI.
- ``trace_to_binary``: text trace → packed binary ("TRAC" format) and back.

Style: real files, real round-trips, observable behavior. No mocks — these
modules are pure and fast.
"""
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parent.parent.parent
ENV = {**{"PYTHONPATH": str(DSE)}, **__import__("os").environ}

from veritx_dse.simulation.trace_to_binary import BINARY_MAGIC, convert_text_to_binary
from veritx_dse.simulation.model_to_trace import (
    COLLECTIVE_DECOMPOSERS,
    alltoall_packets,
    model_to_trace,
    ring_allgather_packets,
    ring_allreduce_packets,
    ring_reducescatter_packets,
    write_trace,
)


# ── trace_to_binary ──────────────────────────────────────────────────────

class TestTraceToBinary:
    def _write_trace(self, tmp_path, lines):
        p = tmp_path / "in.trace"
        p.write_text("\n".join(lines) + "\n")
        return p

    def test_round_trip_binary_format(self, tmp_path):
        src = self._write_trace(tmp_path, [
            "# comment line is skipped",
            "% also a comment",
            "100 0 0 1 4",
            "50 1 0 2 8",       # out of order on purpose: must be sorted
            "garbage line ignored",
            "300 2 0 3 4",
        ])
        dst = tmp_path / "out.bin"
        convert_text_to_binary(str(src), str(dst))
        data = dst.read_bytes()
        magic, count = struct.unpack_from("<II", data, 0)
        assert magic == BINARY_MAGIC
        assert count == 3
        # 16-byte records (<QHHHH), per the module's documented format
        records = [struct.unpack_from("<QHHHH", data, 8 + i * 16) for i in range(count)]
        assert records == [
            (50, 1, 0, 2, 8),     # sorted by cycle
            (100, 0, 0, 1, 4),
            (300, 2, 0, 3, 4),
        ]
        assert len(data) == 8 + count * 16

    def test_empty_trace_yields_header_only(self, tmp_path):
        src = self._write_trace(tmp_path, ["# nothing here"])
        dst = tmp_path / "out.bin"
        convert_text_to_binary(str(src), str(dst))
        data = dst.read_bytes()
        assert struct.unpack_from("<II", data) == (BINARY_MAGIC, 0)
        assert len(data) == 8

    def test_cli_usage_error(self, tmp_path):
        r = subprocess.run(
            [sys.executable, str(DSE / "veritx_dse" / "simulation" / "trace_to_binary.py")],
            capture_output=True, text=True, env=ENV, timeout=30)
        assert r.returncode == 1
        assert "Usage:" in r.stdout

    def test_cli_conversion(self, tmp_path):
        src = self._write_trace(tmp_path, ["7 3 0 4 2"])
        dst = tmp_path / "cli.bin"
        r = subprocess.run(
            [sys.executable, str(DSE / "veritx_dse" / "simulation" / "trace_to_binary.py"),
             str(src), str(dst)],
            capture_output=True, text=True, env=ENV, timeout=30)
        assert r.returncode == 0
        assert "Converted 1 entries" in r.stdout
        assert struct.unpack_from("<II", dst.read_bytes()) == (BINARY_MAGIC, 1)


# ── model_to_trace: collective decomposers ───────────────────────────────

class TestDecomposers:
    def test_allreduce_ring_shape(self):
        # 4 participants ⇒ 2(k-1)=6 steps × k sends = 24 packets
        pkts = ring_allreduce_packets([0, 1, 2, 3], total_bytes=1024, ipc=0.5)
        assert len(pkts) == 24
        assert all(len(p) == 5 for p in pkts)
        # ring topology: each step is 0→1→2→3→0
        assert pkts[0] == (0, 0, 0, 1, 4) and pkts[1] == (2, 1, 0, 2, 4)

    def test_degenerates_to_empty_for_single_participant(self):
        assert ring_allreduce_packets([5], 1024) == []
        assert ring_allgather_packets([5], 1024) == []
        assert ring_reducescatter_packets([5], 1024) == []
        assert alltoall_packets([5], 1024) == []

    def test_allgather_and_reducescatter_are_k_minus_1_steps(self):
        ga = ring_allgather_packets([0, 1, 2], 512)
        rs = ring_reducescatter_packets([0, 1, 2], 512)
        assert len(ga) == len(rs) == 3 * 2  # (k-1) steps × k sends

    def test_alltoall_is_all_pairs(self):
        pkts = alltoall_packets([0, 1, 2], 512)
        assert len(pkts) == 6  # k(k-1)
        assert {(p[1], p[3]) for p in pkts} == {(i, j) for i in range(3) for j in range(3) if i != j}

    def test_accurate_scaling_grows_packet_size(self):
        small = ring_allreduce_packets([0, 1], total_bytes=256)
        big = ring_allreduce_packets([0, 1], total_bytes=256 * 1000, accurate=True)
        assert max(p[4] for p in small) == 4                     # floor
        assert max(p[4] for p in big) > 4                        # bytes/64B per flit


class TestDecomposerRegistry:
    def test_uppercase_aliases_resolve_to_same_functions(self):
        for name in ("allreduce", "allgather", "reducescatter", "alltoall"):
            assert COLLECTIVE_DECOMPOSERS[name.upper()] is COLLECTIVE_DECOMPOSERS[name]


# ── model_to_trace: the converter ────────────────────────────────────────

def _traffic_model():
    """Minimal unified TrafficModel: two flow classes, two instances each."""
    return {
        "network": {
            "flow_classes": [
                {
                    "name": "tp_allreduce",
                    "comm_type": "allreduce",
                    "bytes_per_invocation": 4096,
                    "invocations_per_batch": 2,
                    "instances": [{"participants": [0, 1, 2, 3]},
                                  {"participants": [4, 5, 6, 7]}],
                },
                {
                    "name": "ep_alltoall",
                    "comm_type": "ALLTOALL",   # uppercase alias must work
                    "bytes_per_invocation": 1024,
                    "invocations_per_batch": 1,
                    "instances": [{"participants": [0, 1, 2, 3]}],
                },
            ]
        }
    }


class TestModelToTrace:
    def test_converts_all_classes_and_instances(self):
        pkts = model_to_trace(_traffic_model(), n_nodes=8)
        # allreduce: 2 invocations × 2 instances × 24 pkts; alltoall: 4×3 pairs
        assert len(pkts) == 2 * 2 * 24 + 12
        # BookSim class mapping: everything lands in class 0
        assert all(p[2] == 0 for p in pkts)
        # sorted by (cycle, src)
        keys = [(p[0], p[1]) for p in pkts]
        assert keys == sorted(keys)

    def test_out_of_range_participants_dropped(self):
        tm = {"network": {"flow_classes": [{
            "name": "x", "comm_type": "allreduce", "bytes_per_invocation": 64,
            "invocations_per_batch": 1,
            "instances": [{"participants": [0, 1, 99, -1]}],   # 99/-1 invalid for 2 nodes
        }]}}
        pkts = model_to_trace(tm, n_nodes=2)
        assert all(p[1] in (0, 1) and p[3] in (0, 1) for p in pkts)

    def test_single_participant_instance_skipped(self):
        tm = {"network": {"flow_classes": [{
            "name": "x", "comm_type": "allreduce", "bytes_per_invocation": 64,
            "instances": [{"participants": [0]}],
        }]}}
        assert model_to_trace(tm, n_nodes=4) == []

    def test_unknown_comm_type_is_skipped_with_warning(self, capsys):
        tm = {"network": {"flow_classes": [{
            "name": "weird", "comm_type": "hypercube_shuffle",
            "bytes_per_invocation": 64, "instances": [{"participants": [0, 1]}],
        }]}}
        assert model_to_trace(tm, n_nodes=2) == []
        assert "unknown comm_type" in capsys.readouterr().err

    def test_write_trace_round_trips_through_parser(self, tmp_path):
        pkts = model_to_trace(_traffic_model(), n_nodes=8)
        out = tmp_path / "gen.trace"
        n = write_trace(pkts, str(out))
        assert n == len(pkts)
        text = out.read_text()
        assert text.startswith("# Generated from traffic model:")
        body = [tuple(map(int, l.split())) for l in text.splitlines() if not l.startswith("#")]
        assert body == pkts


class TestModelToTraceCLI:
    def test_main_generates_trace_and_reports(self, tmp_path):
        tm_path = tmp_path / "tm.json"
        tm_path.write_text(json.dumps(_traffic_model()))
        out = tmp_path / "out.trace"
        r = subprocess.run(
            [sys.executable, "-m", "veritx_dse.simulation.model_to_trace",
             "--traffic-model", str(tm_path), "--nodes", "8",
             "--out", str(out), "--accurate-volumes"],
            capture_output=True, text=True, env=ENV, cwd=str(DSE), timeout=60)
        assert r.returncode == 0, r.stderr[-500:]
        assert "2 flow classes" in r.stdout
        assert "Generated" in r.stdout and "Estimated IR:" in r.stdout
        assert out.exists()
