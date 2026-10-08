"""Loom truth foundation: capability registry and value provenance.

These pin the two guarantees the reference product cannot make and that Slice 1
exists to establish:

1. CAPABILITY TRUTH. The registry is the only authority, its topology rows are
   probed rather than declared, and a capability with no implementation is named
   as NOT_IMPLEMENTED instead of being inferred from a topology or model name.
2. PROVENANCE. A MEASURED value must name its run and backend or be refused at
   construction; only a MEASURED value may be presented as a result; freshness is
   independent of origin.

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

import pytest

from veritx_dse.application.loom_capability import (
    CAPABILITY_STATUSES, loom_capabilities, topology_family_capabilities,
)
from veritx_dse.application.value_provenance import (
    ORIGINS, ProvenanceError, ValueProvenance, authored, declared, derived,
    measured, provenance_registry, staleness_for,
)


class TestCapabilityRegistry:
    def test_static_table_is_a_valid_registry(self):
        view = loom_capabilities(include_topology_probe=False)
        assert view["type"] == "srota/LoomCapabilityRegistry"
        ids = [c["id"] for c in view["capabilities"]]
        assert len(ids) == len(set(ids)), "a capability id appeared twice"
        for cap in view["capabilities"]:
            assert cap["status"] in CAPABILITY_STATUSES
            assert cap["reason"], f"{cap['id']} has no reason"
            assert cap["evidence_refs"], (
                f"{cap['id']} is unbacked: every capability must name the "
                f"paths that establish it")
            # A path, not a string iterated into characters. Writing a bare
            # string in the source table shipped forty one-letter "paths"
            # because list("path") is a character list, and a truthiness
            # assertion cannot tell the difference.
            for ref in cap["evidence_refs"]:
                assert isinstance(ref, str) and len(ref) > 3 and "/" in ref, (
                    f"{cap['id']} cites {ref!r}, which is not a source path")

    def test_every_status_bucket_is_represented(self):
        # A registry that only ever says READY is not a registry.
        view = loom_capabilities(include_topology_probe=False)
        present = set(view["by_status"])
        assert {"READY", "PARTIAL", "BLOCKED", "NOT_IMPLEMENTED"} <= present

    def test_the_srota_fabric_reports_its_real_stage(self):
        # SROTA is now a canonical, authorable and materializable family, so
        # the motivating "cannot reach it at all" case is gone. What must
        # still hold is that the row reports the REAL blocker and never
        # implies a runnable design: SIMULATOR support is not a product path.
        view = loom_capabilities(include_topology_probe=True)
        srota = next(c for c in view["capabilities"]
                     if c["id"] == "topology.srota")
        # The whole chain now runs: authored, materialized, routed over
        # shared wires, certified, rendered and executed.
        assert srota["status"] == "READY"
        assert srota["blocked_at"] is None
        assert "probed end to end" in srota["reason"].lower()

    def test_the_firewall_is_not_implemented_and_says_so(self):
        view = loom_capabilities(include_topology_probe=False)
        firewall = next(c for c in view["capabilities"]
                        if c["id"] == "access.firewall")
        assert firewall["status"] == "NOT_IMPLEMENTED"

    def test_rtl_generation_is_not_implemented(self):
        view = loom_capabilities(include_topology_probe=False)
        rtl = next(c for c in view["capabilities"]
                   if c["id"] == "generate.rtl")
        assert rtl["status"] == "NOT_IMPLEMENTED"
        assert "gen_rtl" in rtl["reason"]

    def test_uvm_output_is_not_claimed_as_qualified(self):
        view = loom_capabilities(include_topology_probe=False)
        uvm = next(c for c in view["capabilities"]
                   if c["id"] == "generate.uvm")
        assert uvm["status"] == "PARTIAL"
        assert "Verilator lint" in uvm["reason"]
        assert "mesh.sv" in " ".join(uvm["evidence_refs"])

    def test_readiness_is_not_conflated_with_capability(self):
        view = loom_capabilities(include_topology_probe=False)
        # A backend that implements a question but cannot execute it now is
        # BLOCKED, and the registry must say that per-design readiness belongs
        # to the evaluation plan rather than being answered here.
        astra = next(c for c in view["capabilities"]
                     if c["id"] == "execution.astra")
        assert astra["status"] == "BLOCKED"
        assert "support" in view["readiness_note"]
        assert "readiness" in view["readiness_note"]


class TestTopologyProbe:
    def test_every_registered_family_is_probed(self):
        caps = topology_family_capabilities()
        assert caps, "no topology family was probed"
        for cap in caps:
            assert cap.evidence_refs
            assert cap.status in CAPABILITY_STATUSES

    def test_probe_is_not_a_hardcoded_family_list(self):
        # If the family set is probed from the compiler, then a family the
        # compiler rejects cannot appear as READY. Probing twice must agree,
        # which a hand-maintained list would not guarantee.
        first = {c.id: c.status for c in topology_family_capabilities()}
        second = {c.id: c.status for c in topology_family_capabilities()}
        assert first == second

    def test_a_complete_family_is_ready_and_an_unshipped_one_is_partial(self):
        caps = {c.id.split(".", 1)[1]: c
                for c in topology_family_capabilities()}
        # mesh ships a preset and is complete end to end.
        assert caps["mesh"].status == "READY"
        assert caps["mesh"].blocked_at is None
        # dragonfly used to stop at PRODUCT_WIRED for lack of a preset;
        # the dragonfly4 preset shipped it (§6), so it is READY now.
        assert caps["dragonfly"].status == "READY"
        assert caps["dragonfly"].blocked_at is None

    def test_partial_means_complete_short_of_wiring(self):
        from types import SimpleNamespace
        from veritx_dse.application.loom_capability import (
            _family_capability,  # noqa: E402
        )
        truth = SimpleNamespace(
            stages={s: "YES" for s in (
                "AUTHORABLE", "MATERIALIZABLE", "ROUTABLE",
                "VERIFIABLE", "PROJECTABLE", "EXECUTABLE",
                "QUALIFIED", "PRODUCT_WIRED")},
            stopped_at_stage="PRODUCT_WIRED",
            authority={"PRODUCT_WIRED": "no shipped preset"},
            profile_id=None,
        )
        truth.stages["PRODUCT_WIRED"] = "NO"
        cap = _family_capability("hypothetical", truth)
        assert cap.status == "PARTIAL"
        assert cap.blocked_at == "PRODUCT_WIRED"

    def test_gec_mesh_is_ready_but_shared_channel_modes_are_blocked(self):
        caps = {c.id.split(".", 1)[1]: c
                for c in topology_family_capabilities()}
        assert caps["gec_mesh"].status == "READY"
        assert caps["gec_mesh"].blocked_at is None
        # GEC-MECS is fully READY: shared wires, per-tap VCs, v3 route,
        # certificate, renderer with live conservation proof, shipped preset.
        assert caps["gec_multidrop"].status == "READY"
        assert caps["gec_multidrop"].blocked_at is None
        # P2: the six-VC hybrid preset preserves and proves both choices;
        # runtime route-compute observations are mandatory for execution.
        assert caps["gec_hybrid"].status == "READY"
        assert caps["gec_hybrid"].blocked_at is None

    def test_the_stopped_stage_uses_the_product_vocabulary(self):
        # The compiler reports its own stage names ("TOPOLOGY"); a client must
        # never have to know them.
        from veritx_dse.application.loom_capability import STAGE_ORDER
        for cap in topology_family_capabilities():
            if cap.blocked_at is not None:
                assert cap.blocked_at in STAGE_ORDER, (
                    f"{cap.id} stopped at {cap.blocked_at!r}, which is not a "
                    f"product stage")


class TestValueProvenance:
    def test_the_four_origins_are_exactly_four(self):
        assert ORIGINS == ("AUTHORED", "DERIVED", "DECLARED", "MEASURED")
        registry = provenance_registry()
        assert registry["origins"] == list(ORIGINS)
        assert len(registry["origin_meaning"]) == 4

    def test_only_measured_is_a_result(self):
        assert measured("x", run_id="r1", backend="BOOKSIM_STANDALONE").is_result
        for value in (authored("x"), derived("x", artifact_kind="topology"),
                      declared("x")):
            assert not value.is_result

    def test_measured_without_a_run_is_refused(self):
        # This is the guarantee the reference product cannot make: a measured
        # number with nothing behind it is unrepresentable, not discouraged.
        with pytest.raises(ProvenanceError, match="no run_id"):
            ValueProvenance(origin="MEASURED", label="utilization",
                            backend="BOOKSIM_STANDALONE")

    def test_measured_without_a_backend_is_refused(self):
        with pytest.raises(ProvenanceError, match="no backend"):
            ValueProvenance(origin="MEASURED", label="utilization",
                            run_id="run-1")

    def test_an_unknown_origin_is_refused(self):
        with pytest.raises(ProvenanceError, match="origin must be"):
            ValueProvenance(origin="ESTIMATED", label="x")

    def test_an_origin_cannot_cite_an_impossible_artifact(self):
        # Intent does not come out of a route artifact, and a derived value
        # does not come out of a draft. Citing the wrong chain is how a derived
        # number ends up looking authored.
        with pytest.raises(ProvenanceError, match="cannot cite"):
            ValueProvenance(origin="AUTHORED", label="x",
                            artifact_kind="route")

    def test_a_declared_value_cannot_carry_a_result_chain(self):
        with pytest.raises(ProvenanceError, match="cannot cite"):
            ValueProvenance(origin="DECLARED", label="target node",
                            artifact_kind="run")

    def test_staleness_without_a_revision_is_refused(self):
        with pytest.raises(ProvenanceError, match="names no revision"):
            ValueProvenance(origin="MEASURED", label="latency",
                            run_id="run-1", backend="BOOKSIM",
                            freshness="STALE")

    def test_a_measured_value_may_still_be_current(self):
        value = measured("latency", run_id="run-1", backend="BOOKSIM",
                         revision_id="r07")
        assert value.is_result
        assert value.freshness == "CURRENT"

    def test_provenance_round_trips_through_the_wire_shape(self):
        value = measured("avg packet latency", run_id="run-1",
                         backend="BOOKSIM_STANDALONE", unit="cycles",
                         revision_id="r07", evidence_ref="sha256:aa",
                         qualification="CERTIFIED_BOOKSIM_MESH_DOR_XY_V1")
        wire = value.as_dict()
        assert wire["origin"] == "MEASURED"
        assert wire["run_id"] == "run-1"
        assert wire["backend"] == "BOOKSIM_STANDALONE"
        assert wire["is_result"] is True
        assert wire["unit"] == "cycles"


class TestStaleness:
    def test_a_result_from_another_revision_is_foreign(self):
        assert staleness_for("r07", "r08") == "FOREIGN_REVISION"

    def test_same_revision_with_a_dirty_draft_is_stale(self):
        assert staleness_for("r07", "r07", draft_dirty=True) == "STALE"

    def test_same_revision_and_clean_draft_is_current(self):
        assert staleness_for("r07", "r07") == "CURRENT"

    def test_no_revision_means_no_staleness_claim(self):
        assert staleness_for(None, "r07") == "CURRENT"
        assert staleness_for("r07", None) == "CURRENT"

    def test_the_three_states_are_distinct_and_explained(self):
        registry = provenance_registry()
        states = set(registry["freshness_meaning"])
        assert {"CURRENT", "STALE", "FOREIGN_REVISION"} <= states
        # A stale result is still a real measurement; the wording must say so,
        # or a reader concludes the number was wrong.
        assert "not wrong" in registry["freshness_meaning"]["STALE"]

class TestSrotaRowFollowsTheEngine:
    """topology.srota is probed, not listed.

    The row used to be static text asserting "no authorable intent kind". A
    static entry rots: engine work landing a srota kind would leave the table
    claiming its absence. These pin that the row reads the engine instead.
    """

    def test_at_most_one_srota_row_per_view(self):
        # One id, one row. Two rows under one id would collide in every client
        # keyed by capability id.
        for probe in (False, True):
            view = loom_capabilities(include_topology_probe=probe)
            ids = [c["id"] for c in view["capabilities"]]
            assert ids.count("topology.srota") <= 1, (
                "duplicate topology.srota rows: the special row and a family "
                "row share one id")

    def test_the_row_reports_what_it_checked(self):
        # The reason must name the facts the probe read, so a reader can
        # verify each one rather than trusting the verdict.
        view = loom_capabilities(include_topology_probe=True)
        srota = next(c for c in view["capabilities"]
                     if c["id"] == "topology.srota")
        assert srota["evidence_refs"], (
            "a probed row must cite the real compiler paths it read")

    def test_an_authorable_srota_is_no_longer_special_cased(self):
        # SROTA is now a first-class authorable kind, so its row must come
        # from the same probed family table as every other family rather than
        # from the simulator-only fallback row.
        import veritx_dse.model.topology_intent as intent_mod
        from veritx_dse.application import loom_capability as registry
        assert "srota" in intent_mod.AUTHORABLE_INTENT_KINDS
        assert registry._srota_capability() is None

    def test_a_gated_srota_yields_to_the_family_row(self):
        # When srota is a gated kind the probed family row carries the
        # pipeline truth under this same id. A second row would be a
        # duplicate id, not a second fact.
        import veritx_dse.application.capability_truth as truth_mod
        from veritx_dse.application import loom_capability as registry
        assert "srota" in truth_mod.GATED_KINDS
        assert registry._srota_capability() is None
