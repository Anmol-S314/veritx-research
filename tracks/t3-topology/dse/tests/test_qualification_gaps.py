"""Qualification gaps closed: cycle-accurate parity, formal proofs, estimators.

Every test here is labeled by the number it actually measures:

* parity: same 5-packet trace into BookSim and the Verilator TB;
  delivered payloads, flit counts, drain cycles, latency populations,
  with observed cycle deltas recorded (never forced equal). PASS requires
  the tools to run; without them the verdict is a typed NOT_RUN.

* formal: unbounded ``sby prove`` (COMPLETE scope) for M1 address-decode
  exclusivity and for 2-VC mesh CDG acyclicity (Dally-Seitz witness).
  Counterexamples fail loudly; missing tools are typed NOT_RUN.

* physical estimators: congestion (HPWL load + region density), wire
  delay per plane, clock-tree far-point per domain — all planning
  estimates only — plus typed NOT_RUN slack/skew (no Liberty/PDK/
  OpenSTA in this environment).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from veritx_dse.product.ordering_fsm_rtl import (  # noqa: E402
    SMOKE_TRACE_TEXT,
    _compare_delivered_payloads,
    _expected_packets_from_trace,
    _parse_ejection_log,
    _parse_results_counts,
    run_booksim_rtl_parity_smoke,
)
from veritx_dse.product.formal_proofs import (  # noqa: E402
    COMPLETE_SCOPE, REQUIRED_TOOLS, CyclicCdg, render_cdg_sv,
    render_m1_exclusivity_sv, run_formal_proofs, topo_ranks,
)
from veritx_dse.product.floorplan import (  # noqa: E402
    PLANNING_SCOPE, Floorplan, WireModel, derive, estimate_planning,
)
from veritx_dse.model.physical_placement import RouterFootprint  # noqa: E402

REPO = DSE.parent.parent.parent
RTLGEN = (REPO / "tracks" / "t3-topology" / "scripts" / "rtlgen" / "gen_rtl.py")

TINY4_ANYNET = """\
router 0 node 0 router 1 router 2
router 1 node 1 router 0 router 3
router 2 node 2 router 0 router 3
router 3 node 3 router 1 router 2
"""


def _sha_doc(doc) -> str:
    body = json.dumps(doc, sort_keys=True, separators=(",", ":"),
                      default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _formal_tools_present() -> bool:
    return all(shutil.which(tool) for tool in REQUIRED_TOOLS)


# ---------------------------------------------------------------------------
# Cycle-accurate parity
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parity_rtl_dir(tmp_path_factory):
    """Emitted RTL for the 2x2 mesh (Verilator build happens in the smoke)."""
    work = tmp_path_factory.mktemp("qual-parity")
    anynet = work / "probe.anynet"
    anynet.write_text(TINY4_ANYNET)
    rtl_dir = work / "rtl"
    proc = subprocess.run(
        [sys.executable, str(RTLGEN), "--anynet", str(anynet),
         "--outdir", str(rtl_dir), "--num-vc", "2", "--buf", "8"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert (rtl_dir / "noc_top.sv").is_file()
    return rtl_dir, anynet


@pytest.fixture(scope="module")
def parity_verdict(parity_rtl_dir):
    rtl_dir, anynet = parity_rtl_dir
    return run_booksim_rtl_parity_smoke(rtl_dir=rtl_dir, anynet=anynet)


class TestParityCycleAccurate:
    def test_harness_verdict_is_typed_either_way(self, parity_verdict):
        assert parity_verdict["status"] in ("PASS", "NOT_RUN", "FAIL")
        if parity_verdict["status"] == "NOT_RUN":
            # Typed, named harness reason — never a silent skip.
            assert parity_verdict["code"] == "PARITY_HARNESS_UNAVAILABLE"
            assert "unavailable" in (parity_verdict["reason"] or "")
            return
        assert parity_verdict["status"] == "PASS", parity_verdict["reason"]
        assert parity_verdict["code"] == "PARITY_PASS"

    def test_cycle_numbers_actually_measured(self, parity_verdict):
        if parity_verdict["status"] != "PASS":
            pytest.skip("parity harness unavailable; numbers not measured")
        cycle = parity_verdict["cycle_accurate"]
        # Drain cycles measured on both sides (last-delivery cycle).
        assert cycle["drain_cycles"]["booksim"] is not None
        assert cycle["drain_cycles"]["rtl"] is not None
        # Observed delta recorded as a number; equality not forced.
        assert isinstance(cycle["drain_delta_cycles"], int)
        assert cycle["cycle_exact"] == (cycle["drain_delta_cycles"] == 0)
        assert parity_verdict["rtl"]["drain_cycles"] == \
            cycle["drain_cycles"]["rtl"]
        assert parity_verdict["booksim"]["drain_cycles"] == \
            cycle["drain_cycles"]["booksim"]
        # Observed values on this pinned harness (4 routers, 5 packets).
        # 2026-11-10: the router's arbiter gained a registered pipeline stage,
        # so the RTL path is one stage slower (drain 12 -> 17) while the gap to
        # BookSim tightened (delta 8 -> 3). Both sides re-measured.
        assert cycle["n_routers"] == 4
        assert cycle["packet_count"] == 5
        assert cycle["drain_cycles"]["booksim"] == 20
        assert cycle["drain_cycles"]["rtl"] == 17
        assert cycle["drain_delta_cycles"] == 3
        assert cycle["cycle_exact"] is False  # honest: deltas are nonzero

    def test_delivered_payloads_exact_and_flit_counts(self, parity_verdict):
        if parity_verdict["status"] != "PASS":
            pytest.skip("parity harness unavailable")
        payloads = parity_verdict["delivered_payloads"]
        assert payloads["match"] is True
        assert payloads["expected_by_pair"] == payloads["observed_by_pair"]
        assert payloads["expected_by_pair"] == {
            "0->3": 4, "1->2": 2, "2->0": 2, "3->1": 2}
        assert payloads["expected_types"] == payloads["observed_types"]
        assert payloads["observed_types"] == {0: 5, 1: 0, 2: 5, 3: 0}
        # Flit counts: overall and per class (BookSim side).
        assert parity_verdict["booksim"]["flits_injected"] == 10
        assert parity_verdict["booksim"]["flits_accepted"] == 10
        assert parity_verdict["booksim"]["flits_by_class"] == {
            0: {"injected": 6, "accepted": 6},
            1: {"injected": 4, "accepted": 4}}
        assert parity_verdict["rtl"]["injected"] == 10
        assert parity_verdict["rtl"]["ejected"] == 10
        # Per-flit ejection log is complete (10 < TB 30-cap).
        assert len(parity_verdict["rtl"]["ejection_log"]) == 10
        assert parity_verdict["rtl"]["ejection_log_truncated"] is False

    def test_latency_populations_labeled_not_equated(self, parity_verdict):
        if parity_verdict["status"] != "PASS":
            pytest.skip("parity harness unavailable")
        latency = parity_verdict["cycle_accurate"]["latency"]
        assert latency["booksim_flit_latency_avgs_by_class"] == [15.333, 14.5]
        assert latency["rtl_packet_latency_mean"] == 9.8  # 2026-11-10: +1 pipeline stage
        assert isinstance(latency["delta"], float)
        assert "populations differ" in latency["scope"]

    def test_smoke_is_deterministic(self, parity_rtl_dir):
        rtl_dir, anynet = parity_rtl_dir
        first = run_booksim_rtl_parity_smoke(rtl_dir=rtl_dir, anynet=anynet)
        second = run_booksim_rtl_parity_smoke(rtl_dir=rtl_dir, anynet=anynet)
        assert _sha_doc(first) == _sha_doc(second)


class TestParityHelpers:
    def test_missing_binary_is_typed_not_run(self, tmp_path):
        verdict = run_booksim_rtl_parity_smoke(
            rtl_dir=tmp_path / "rtl", anynet=tmp_path / "x.anynet",
            booksim_bin=Path(tmp_path / "no-booksim"))
        assert verdict["status"] == "NOT_RUN"
        assert verdict["code"] == "PARITY_HARNESS_UNAVAILABLE"
        assert "BookSim" in (verdict["reason"] or "")
        assert verdict["booksim"] is None and verdict["rtl"] is None

    def test_parsers_read_real_tb_output(self):
        log = "".join(
            f"    EJ cyc={c} r={r} src={s} dst={d} seq=1 typ={t}\n"
            for c, r, s, d, t in (
                (5, 0, 2, 0, 0), (6, 3, 0, 3, 2)))
        rows = _parse_ejection_log(log)
        assert rows == [
            {"cyc": 5, "router": 0, "src": 2, "dst": 0, "seq": 1, "typ": 0},
            {"cyc": 6, "router": 3, "src": 0, "dst": 3, "seq": 1, "typ": 2}]
        counts = _parse_results_counts(
            "injected:      10 (free=3, esc=2)\nwrong_dst:     0 OK\n")
        assert counts == {"free_packets": 3, "esc_packets": 2,
                          "wrong_dst": 0}

    def test_payload_comparison_catches_mismatch(self):
        packets = _expected_packets_from_trace(SMOKE_TRACE_TEXT, 4)
        assert [ (p["src"], p["dst"]) for p in packets ] == [
            (0, 3), (1, 2), (2, 0), (3, 1), (0, 3)]
        good = _compare_delivered_payloads(packets, [
            {"cyc": 1, "router": 0, "src": 0, "dst": 3, "seq": 1, "typ": 0},
            {"cyc": 2, "router": 0, "src": 0, "dst": 3, "seq": 1, "typ": 2},
            {"cyc": 1, "router": 1, "src": 1, "dst": 2, "seq": 1, "typ": 0},
            {"cyc": 2, "router": 1, "src": 1, "dst": 2, "seq": 1, "typ": 2},
            {"cyc": 1, "router": 2, "src": 2, "dst": 0, "seq": 1, "typ": 0},
            {"cyc": 2, "router": 2, "src": 2, "dst": 0, "seq": 1, "typ": 2},
            {"cyc": 1, "router": 3, "src": 3, "dst": 1, "seq": 1, "typ": 0},
            {"cyc": 2, "router": 3, "src": 3, "dst": 1, "seq": 1, "typ": 2},
            {"cyc": 3, "router": 0, "src": 0, "dst": 3, "seq": 2, "typ": 0},
            {"cyc": 4, "router": 0, "src": 0, "dst": 3, "seq": 2, "typ": 2},
        ], 10)
        assert good["match"] is True
        bad = _compare_delivered_payloads(packets, [
            {"cyc": 1, "router": 0, "src": 0, "dst": 3, "seq": 1, "typ": 0},
        ], 10)
        assert bad["match"] is None  # truncated log: incomplete, not exact
        assert "truncated" in bad["scope"]


# ---------------------------------------------------------------------------
# Formal proofs
# ---------------------------------------------------------------------------


class TestFormalCompleteness:
    def test_m1_and_cdg_pass_with_complete_scope(self, tmp_path):
        manifest = run_formal_proofs(work_dir=tmp_path / "formal")
        if not _formal_tools_present():
            assert manifest["status"] == "NOT_RUN"
            assert manifest["code"] == "FORMAL_HARNESS_UNAVAILABLE"
            assert "missing" in (manifest["reason"] or "")
            return
        assert manifest["status"] == "PASS", manifest["reason"]
        by_id = {p["id"]: p for p in manifest["proofs"]}
        m1 = by_id["m1_address_decode_exclusivity"]
        cdg = by_id["cdg_acyclicity_2vc_mesh"]
        assert m1["status"] == "PASS" and m1["scope"] == COMPLETE_SCOPE
        assert cdg["status"] == "PASS" and cdg["scope"] == COMPLETE_SCOPE
        assert cdg["stats"]["routers"] == 16  # 4x4 mesh
        assert cdg["stats"]["free"]["edges"] == 68
        assert cdg["stats"]["esc"]["edges"] == 38
        assert cdg["cross_check"]["cdg_has_cycle_emitter"] is False

    def test_overlapping_ranges_fail_the_m1_proof(self, tmp_path):
        overlap = SimpleNamespace(
            entries=(
                SimpleNamespace(name="A", base=0x1000, size=0x2000,
                                target_agent_group=0, target_endpoint_id=0,
                                selection_policy=None,
                                target_instance_index=None,
                                interleave_bytes=None,
                                target_endpoint_ids=()),
                SimpleNamespace(name="B", base=0x2000, size=0x1000,
                                target_agent_group=0, target_endpoint_id=1,
                                selection_policy=None,
                                target_instance_index=None,
                                interleave_bytes=None,
                                target_endpoint_ids=()),
            ),
            address_decode_hash="")
        manifest = run_formal_proofs(work_dir=tmp_path / "overlap",
                                     decode=overlap)
        by_id = {p["id"]: p for p in manifest["proofs"]}
        # Counterexample found: FAIL, never a faked PASS.
        assert by_id["m1_address_decode_exclusivity"]["status"] == "FAIL"
        assert "counterexample" in by_id["m1_address_decode_exclusivity"][
            "reason"]
        assert manifest["status"] == "FAIL"
        # The CDG obligation is unaffected by the decoder map.
        assert by_id["cdg_acyclicity_2vc_mesh"]["status"] == "PASS"

    def test_cyclic_tables_have_no_rank_witness(self):
        # Triangle with routes 0->2 via 1, 1->0 via 2, 2->1 via 0: 3-cycle.
        adj = {0: {1, 2}, 1: {0, 2}, 2: {0, 1}}
        direct = {(0, 1): 0, (0, 2): 1, (1, 0): 0, (1, 2): 1,
                  (2, 0): 0, (2, 1): 1}
        cyclic = dict(direct)
        cyclic[(0, 2)] = 0  # 0->{1}
        cyclic[(1, 0)] = 1  # 1->{2}
        cyclic[(2, 1)] = 0  # 2->{0}
        with pytest.raises(CyclicCdg):
            render_cdg_sv(3, adj, {"free": cyclic, "esc": direct})

    def test_rank_witness_respects_every_edge(self):
        from veritx_dse.product.formal_proofs import cdg_edges
        adj = {0: {1, 2}, 1: {0, 3}, 2: {0, 3}, 3: {1, 2}}
        tbl = {(0, 1): 0, (0, 2): 1, (1, 0): 0, (1, 3): 1,
               (2, 0): 0, (2, 3): 1, (3, 1): 0, (3, 2): 1}
        edges = cdg_edges(4, adj, tbl)
        rank = topo_ranks(edges)
        assert rank is not None
        assert all(rank[u] < rank[v] for u, v in edges)

    def test_formal_manifest_is_deterministic(self, tmp_path):
        first = run_formal_proofs(work_dir=tmp_path / "a")
        second = run_formal_proofs(work_dir=tmp_path / "b")
        assert [ (p["id"], p["status"], p["scope"]) for p in first["proofs"]] == \
            [ (p["id"], p["status"], p["scope"]) for p in second["proofs"]]
        if first["status"] == "PASS":
            assert _sha_doc(first["proofs"]) == _sha_doc(second["proofs"])

    def test_m1_wrapper_emits_assertions(self):
        from veritx_dse.model.address_decode import (
            AddressDecodeArtifact, AddressDecodeEntry, AddressTransform,
            UnmatchedAddressPolicy,
        )
        artifact = AddressDecodeArtifact(
            attachment_hash="a" * 64,
            entries=(AddressDecodeEntry(
                name="HBM0", base=0x1000, size=0x1000,
                target_agent_group=0, target_endpoint_id=0),),
            address_transform=AddressTransform.IDENTITY,
            unmatched_address_policy=UnmatchedAddressPolicy.ERROR,
            schema_version=3)
        source = render_m1_exclusivity_sv(artifact)
        assert "module m1_exclusivity_top" in source
        assert "assert(!overlap_w)" in source


# ---------------------------------------------------------------------------
# Physical estimators
# ---------------------------------------------------------------------------


def _mesh4_fixture():
    topology = {
        "topology_hash": "sha256:" + "a" * 64,
        "routers": [{"router_id": i, "coordinates": [i % 2, i // 2]}
                    for i in range(4)],
        "channels": [
            {"src_router": 0, "dst_router": 1},
            {"src_router": 1, "dst_router": 0},
            {"src_router": 0, "dst_router": 2},
            {"src_router": 2, "dst_router": 0},
            {"src_router": 1, "dst_router": 3},
            {"src_router": 3, "dst_router": 1},
            {"src_router": 2, "dst_router": 3},
            {"src_router": 3, "dst_router": 2},
        ],
        "endpoints": [{"endpoint_id": i, "router_id": i, "group_index": i}
                      for i in range(4)],
        "planes": ["d"],
    }
    plan = Floorplan(
        topology_hash="sha256:" + "a" * 64,
        die_width_um=3800, die_height_um=3800,
        routers=tuple(RouterFootprint(
            router_id=i, x_um=(i % 2) * 2000, y_um=(i // 2) * 2000,
            width_um=800, height_um=800) for i in range(4)),
        keepouts=(), wire=WireModel(ps_per_mm=120, fixed_ps=40))
    return topology, plan


class TestPhysicalEstimators:
    def test_congestion_hpwl_load_and_density(self):
        topology, plan = _mesh4_fixture()
        est = derive(topology, plan)["physical_estimates"]
        assert est["scope"] == PLANNING_SCOPE
        congestion = est["congestion"]
        assert "HPWL_net" in congestion["formula"]
        # Each router sees 4 incident 2000 um nets on an 800x800 macro:
        # load = (4*2000) / (2*(800+800)) = 2.5.
        assert congestion["per_router"] == [
            {"router_id": i, "incident_channels": 4,
             "incident_hpwl_um": 8000.0, "load": 2.5} for i in range(4)]
        assert congestion["load_stats"] == {"min": 2.5, "mean": 2.5,
                                            "max": 2.5}
        # 2x2 regions of 1900x1900 um, one router each.
        assert congestion["max_density"] == 0.177285
        assert all(r["density"] == 0.177285
                   for r in congestion["density_by_region"])
        assert len(congestion["density_by_region"]) == 4

    def test_wire_delay_per_plane_matches_model(self):
        topology, plan = _mesh4_fixture()
        est = derive(topology, plan)["physical_estimates"]
        wire = est["wire_delay_by_plane"]
        assert wire["status"] == "ESTIMATED"
        assert "ps_per_mm" in wire["formula"]
        # 2000 um = 2 mm: 2*120 + 40 = 280 ps on every channel.
        assert wire["by_plane"]["d"]["delay_ps"] == {
            "count": 8, "min": 280.0, "mean": 280.0, "max": 280.0}
        assert wire["by_plane"]["d"]["length_um"] == {
            "count": 8, "min": 2000.0, "mean": 2000.0, "max": 2000.0}
        assert wire["overall"]["delay_ps"]["mean"] == 280.0

    def test_clock_tree_far_point_by_domain(self):
        topology, plan = _mesh4_fixture()
        est = derive(topology, plan)["physical_estimates"]
        clock = est["clock_tree"]
        assert "NOT a CTS" not in clock["formula"]  # formula is distance only
        domains = {d["domain"]: d for d in clock["domains"]}
        # Router centres: R0 (400,400), R1 (2400,400), R2 (400,2400),
        # R3 (2400,2400) on a 3800 um die.
        assert domains["0"]["far_point_um"] == 6800.0
        assert domains["0"]["centre_distance_um"] == 3000.0
        assert domains["1"]["far_point_um"] == 5800.0
        assert domains["3"]["far_point_um"] == 4800.0
        assert "surrogate" in clock["domain_source"]
        # Explicit clock-domain map replaces the surrogate grouping.
        est2 = estimate_planning(topology, plan,
                                 clock_domains={0: "core", 1: "core",
                                                2: "core", 3: "core"})
        assert est2["clock_tree"]["domains"] == [
            {"domain": "core", "members": [0, 1, 2, 3],
             "far_point_um": 6800.0, "centre_distance_um": 3000.0}]

    def test_slack_and_skew_are_typed_not_run_never_zero(self):
        topology, plan = _mesh4_fixture()
        est = derive(topology, plan)["physical_estimates"]
        for key in ("slack_estimate", "cts_skew_estimate"):
            row = est[key]
            assert row["status"] == "NOT_RUN"
            assert row["reason"] == ("no Liberty/PDK/OpenSTA in this "
                                     "environment")
            assert row["estimate_ps"] is None  # typed, not zero

    def test_every_estimator_labeled_planning_only(self):
        topology, plan = _mesh4_fixture()
        est = derive(topology, plan)["physical_estimates"]
        assert len(est["assumptions"]) == 3
        assert all("planning estimate only" in row for row in est["assumptions"])
        for key in ("congestion", "wire_delay_by_plane", "clock_tree"):
            assert est[key].get("formula"), key

    def test_estimators_are_deterministic_and_hash_stable(self):
        topology, plan = _mesh4_fixture()
        first = derive(topology, plan)["physical_estimates"]
        second = derive(topology, plan)["physical_estimates"]
        assert first == second
        assert _sha_doc(first) == _sha_doc(second)
        # JSON round-trip preserves the estimators exactly.
        assert json.loads(json.dumps(first)) == first

    def test_multi_plane_split_is_typed_not_run(self):
        topology, plan = _mesh4_fixture()
        topology = {**topology, "planes": ["d", "c"]}
        est = derive(topology, plan)["physical_estimates"]
        wire = est["wire_delay_by_plane"]
        assert wire["status"] == "NOT_RUN"
        assert "no plane" in wire["reason"]
        assert wire["overall"]["delay_ps"]["mean"] == 280.0  # still surfaced

    def test_unattached_router_is_its_own_domain(self):
        topology, plan = _mesh4_fixture()
        topology = {**topology, "endpoints": [
            e for e in topology["endpoints"] if e["router_id"] != 3]}
        est = derive(topology, plan)["physical_estimates"]
        domains = {d["domain"]: d for d in est["clock_tree"]["domains"]}
        assert domains["unattached:R3"]["members"] == [3]
        assert domains["unattached:R3"]["far_point_um"] == 4800.0

    def test_derive_keeps_existing_keys(self):
        topology, plan = _mesh4_fixture()
        derived = derive(topology, plan)
        assert derived["die"] == {"width_um": 3800, "height_um": 3800,
                                  "area_um2": 3800 * 3800}
        assert derived["links"]["delay_ps"] == {
            "min": 280.0, "mean": 280.0, "max": 280.0}
        assert derived["scope"] == "AUTHORED_FLOORPLAN_NOT_PPA"
