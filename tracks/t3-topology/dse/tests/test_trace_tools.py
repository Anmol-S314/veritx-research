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
    LoweringError,
    alltoall_packets,
    broadcast_packets,
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

    def test_out_of_range_participant_fails_closed(self):
        """PR C: out-of-range participants are a hard error, never a silent
        filter (the old filter made the workload lighter than declared)."""
        tm = {"network": {"flow_classes": [{
            "name": "x", "comm_type": "allreduce", "bytes_per_invocation": 64,
            "invocations_per_batch": 1,
            "instances": [{"participants": [0, 1, 99, -1]}],   # 99/-1 invalid for 2 nodes
        }]}}
        with pytest.raises(LoweringError, match="participant"):
            model_to_trace(tm, n_nodes=2)

    def test_single_participant_instance_fails_closed(self):
        """PR C: a degenerate 1-participant instance is a hard error —
        it used to be silently skipped (workload silently lighter)."""
        tm = {"network": {"flow_classes": [{
            "name": "x", "comm_type": "allreduce", "bytes_per_invocation": 64,
            "instances": [{"participants": [0]}],
        }]}}
        with pytest.raises(LoweringError, match="participant"):
            model_to_trace(tm, n_nodes=4)

    def test_unknown_comm_type_fails_closed(self):
        """PR C: unknown comm_type raises LoweringError naming the class and
        the defect — never warning-and-skip (the BROADCAST-class bug)."""
        tm = {"network": {"flow_classes": [{
            "name": "weird", "comm_type": "hypercube_shuffle",
            "bytes_per_invocation": 64, "instances": [{"participants": [0, 1]}],
        }]}}
        with pytest.raises(LoweringError, match="hypercube_shuffle"):
            model_to_trace(tm, n_nodes=2)

    def test_p2p_is_decomposed(self):
        """P2P flows (e.g. automotive lidar_fusion / camera_fusion) should
        produce point-to-point packets, not be skipped as unknown.

        Regression for automotive_real.json, whose flow classes used
        comm_type 'P2P' and emitted 0 packets before the decomposer existed.
        """
        tm = {"network": {"flow_classes": [{
            "name": "lidar_fusion", "comm_type": "P2P",
            "bytes_per_invocation": 1290,
            "invocations_per_batch": 23716,
            "instances": [{"participants": [0, 1]}],
        }, {
            "name": "camera_fusion", "comm_type": "p2p",
            "bytes_per_invocation": 1419,
            "invocations_per_batch": 22684,
            "instances": [{"participants": [2, 1]}],
        }]}}
        pkts = model_to_trace(tm, n_nodes=4, ipc=1.0)
        # Each invocation = 1 P2P packet. 23716 + 22684 = 46400 total.
        assert len(pkts) == 46400
        # lidar_fusion: src=0 → dst=1 ; camera_fusion: src=2 → dst=1
        assert pkts[0][1] == 0 and pkts[0][3] == 1  # lidar_fusion first packet
        assert pkts[-1][1] == 2 and pkts[-1][3] == 1  # camera_fusion last packet
        # lidar packets all go 0→1 ; camera packets all go 2→1
        lidar = [p for p in pkts if p[1] == 0]
        camera = [p for p in pkts if p[1] == 2]
        assert len(lidar) == 23716
        assert len(camera) == 22684
        assert all(p[3] == 1 for p in lidar)
        assert all(p[3] == 1 for p in camera)
        assert all(p[0] >= 0 for p in pkts)  # non-negative cycles

    def test_p2p_accurate_volumes(self):
        """With --accurate-volumes, P2P packets carry flits sized to the byte
        volume (bytes_per_invocation / 64B per flit), not the 4-flits default.
        """
        tm = {"network": {"flow_classes": [{
            "name": "sensor_fusion", "comm_type": "P2P",
            "bytes_per_invocation": 1290,
            "invocations_per_batch": 1,
            "instances": [{"participants": [3, 7]}],
        }]}}
        pkts = model_to_trace(tm, n_nodes=8, ipc=1.0, accurate=True)
        assert len(pkts) == 1
        # 1290B / 64B per flit = 20.15625 → ceil = 21 flits
        assert pkts[0][4] == 21

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


# ── PR C: fail-closed lowering + LoweringManifest v0 ──────────────────────────

class TestBroadcastDecomposer:
    """PR C §8.3: BROADCAST is precisely defined, not silently deleted.
    The real model automotive_adas.json uses comm_type BROADCAST."""

    def test_broadcast_shape(self):
        pkts = broadcast_packets([0, 1, 2, 3], total_bytes=1024, ipc=0.5)
        assert len(pkts) == 3  # k-1 receivers
        assert all(p[1] == 0 for p in pkts)          # first participant sends
        assert sorted(p[3] for p in pkts) == [1, 2, 3]  # others receive

    def test_broadcast_registered_as_alias(self):
        assert COLLECTIVE_DECOMPOSERS["BROADCAST"] is broadcast_packets
        assert COLLECTIVE_DECOMPOSERS["broadcast"] is broadcast_packets

    def test_real_automotive_adas_model_lowers(self):
        """The actual repo model with a BROADCAST class must lower without
        silent loss (it previously lost camera_frame entirely)."""
        model_path = DSE / "models" / "automotive_adas.json"
        if not model_path.exists():
            pytest.skip("models/automotive_adas.json not present")
        tm = json.loads(model_path.read_text())
        # NOTE: this model ALSO has singleton-participant P2P instances,
        # which fail closed by design — expect the precise error naming it.
        with pytest.raises(LoweringError, match="participant"):
            model_to_trace(tm, n_nodes=64)


class TestLoweringManifest:
    """PR C §6.3: every lowering emits a machine-readable conservation
    manifest; unsupported/dropped are empty by construction."""

    def test_main_writes_manifest_sidecar(self, tmp_path):
        tm_path = tmp_path / "tm.json"
        tm_path.write_text(json.dumps(_traffic_model()))
        out = tmp_path / "out.trace"
        r = subprocess.run(
            [sys.executable, "-m", "veritx_dse.simulation.model_to_trace",
             "--traffic-model", str(tm_path), "--nodes", "8",
             "--out", str(out)],
            capture_output=True, text=True, env=ENV, cwd=str(DSE), timeout=60)
        assert r.returncode == 0, r.stderr[-500:]
        mpath = tmp_path / "out.trace.manifest.json"
        assert mpath.is_file(), "manifest sidecar must be written"
        m = json.loads(mpath.read_text())
        assert m["schema_version"] == 1
        assert m["unsupported_operations"] == []
        assert m["dropped_operations"] == []
        assert m["output"]["packet_count"] > 0
        assert m["output"]["trace_sha256"]

    def test_manifest_conservation_counts(self, tmp_path):
        """Conservation: declared ops map to emitted packets exactly.
        allreduce: 2 inv × 2 inst × 24 pkts; alltoall: 1 × 4×3 pkts."""
        tm_path = tmp_path / "tm.json"
        tm_path.write_text(json.dumps(_traffic_model()))
        out = tmp_path / "out.trace"
        subprocess.run(
            [sys.executable, "-m", "veritx_dse.simulation.model_to_trace",
             "--traffic-model", str(tm_path), "--nodes", "8",
             "--out", str(out)],
            capture_output=True, text=True, env=ENV, cwd=str(DSE), timeout=60,
            check=True)
        m = json.loads((tmp_path / "out.trace.manifest.json").read_text())
        assert m["operation_counts_by_kind"] == {
            "allreduce": 4, "alltoall": 1}
        trace_pkts = [l for l in out.read_text().splitlines()
                      if not l.startswith("#")]
        assert m["output"]["packet_count"] == len(trace_pkts) == 2 * 2 * 24 + 12

    def test_manifest_captures_conversion_params(self, tmp_path):
        tm_path = tmp_path / "tm.json"
        tm_path.write_text(json.dumps(_traffic_model()))
        out = tmp_path / "out.trace"
        subprocess.run(
            [sys.executable, "-m", "veritx_dse.simulation.model_to_trace",
             "--traffic-model", str(tm_path), "--nodes", "8",
             "--out", str(out), "--accurate-volumes"],
            capture_output=True, text=True, env=ENV, cwd=str(DSE), timeout=60,
            check=True)
        m = json.loads((tmp_path / "out.trace.manifest.json").read_text())
        assert m["conversion_parameters"]["accurate_volumes"] is True
        assert m["conversion_parameters"]["bytes_per_flit"] == 64
        # accurate mode: allreduce 4096B over 4-participant ring →
        # bytes/step = 4096/4 = 1024 → 1024/64 = 16 flits/packet
        assert m["output"]["flit_count"] == 2 * 2 * 24 * 16 + 4 * 3 * 4

    def test_failed_lowering_writes_no_trace(self, tmp_path):
        """Fail-closed: a rejected workload produces neither trace nor
        manifest — no partial 'successful' artifact can exist."""
        tm = {"network": {"flow_classes": [{
            "name": "weird", "comm_type": "hypercube_shuffle",
            "bytes_per_invocation": 64, "instances": [{"participants": [0, 1]}],
        }]}}
        tm_path = tmp_path / "tm.json"
        tm_path.write_text(json.dumps(tm))
        out = tmp_path / "out.trace"
        r = subprocess.run(
            [sys.executable, "-m", "veritx_dse.simulation.model_to_trace",
             "--traffic-model", str(tm_path), "--nodes", "8",
             "--out", str(out)],
            capture_output=True, text=True, env=ENV, cwd=str(DSE), timeout=60)
        assert r.returncode != 0
        assert "hypercube_shuffle" in r.stderr
        assert not out.exists()
        assert not (tmp_path / "out.trace.manifest.json").exists()
