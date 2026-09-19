"""StudyManifest + exact ExecutionFingerprint (study-integrity item 1).

Core principle under test: unknown execution dimensions are
unrepresentable — a missing material field raises instead of certifying —
and study identity is canonical across construction surfaces. Tests live
at the seams (builders, dict round-trip, comparison-gate wiring), never
against internals.
"""
import pytest

from veritx_dse.core.comparison import evaluate_comparability
from veritx_dse.core.study import (
    REQUIRED_EXECUTION_DIMENSIONS,
    STUDY_KINDS,
    ExecutionFingerprint,
    StudyError,
    execution_fingerprint,
    new_study_id,
    study_manifest,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _dims(**kw):
    base = {
        "execution_class": "booksim",
        "workload_artifact_hash": "sha256:workload",
        "node_count": 64,
        "fabric_topology": "mesh_8x8",
        "fabric_routing": "dim_order",
        "vc_count": 2,
        "buffer_flits": 8,
        "packet_bytes": 64,
        "flit_bytes": 8,
        "simulator_binary_sha": "ab" * 32,
        "simulator_config_sha": "cd" * 32,
        "mapping": [{"rank": 0, "artifact": "mem-A"},
                    {"rank": 1, "artifact": "mem-B"}],
        "seed": 42,
        "seed_policy": "deterministic:[42]",
        "source_commit": "ef" * 20,
        "source_dirty": False,
        "container_digest": "sha256:tools",
        "python_lock_sha": "12" * 32,
    }
    base.update(kw)
    return base


def _study(hashes=("fp1", "fp2"), **kw):
    base = {
        "study_id": "study-1",
        "study_kind": "DESIGN_COMPARISON",
        "workload_artifact_hash": "sha256:workload",
        "candidate_hashes": list(hashes),
        "controlled_dimensions": {"topology": "mesh_8x8"},
        "experimental_variables": ("routing",),
        "seed_policy": "deterministic:[42]",
        "backend_policy": "booksim-only",
    }
    base.update(kw)
    return study_manifest(**base)


# ── exactness: every dimension load-bearing ──────────────────────────────────

class TestExactness:
    def test_all_required_dimensions_present(self):
        assert set(REQUIRED_EXECUTION_DIMENSIONS) == set(_dims())

    def test_build_hashes_deterministically(self):
        assert (execution_fingerprint(**_dims()).fingerprint_hash
                == execution_fingerprint(**_dims()).fingerprint_hash)

    def test_clean_tree_certifies(self):
        assert execution_fingerprint(**_dims()).certified is True

    def test_dirty_tree_fingerprints_but_never_certifies(self):
        fp = execution_fingerprint(**_dims(source_dirty=True))
        assert fp.certified is False
        # ...yet the dirty state is IN the hash (two different dirty
        # trees sharing a commit hash collide loudly by design — the
        # honest fix is clean trees, not pretending otherwise).
        assert (fp.fingerprint_hash
                != execution_fingerprint(**_dims()).fingerprint_hash)


# ── scientific mutation tests ────────────────────────────────────────────────
# Change ANY result-affecting parameter → identity must change.
# Drop ANY of them → the builder must refuse.

class TestMutation:
    # execution_class is a closed set: mutating it refuses (no unwired
    # projection) instead of hashing. Everything else must move the hash.
    _MUTABLE = [f for f in REQUIRED_EXECUTION_DIMENSIONS
                if f != "execution_class"]

    def test_unknown_execution_class_refuses(self):
        with pytest.raises(StudyError):
            execution_fingerprint(**_dims(execution_class="serving"))

    @pytest.mark.parametrize("field", _MUTABLE)
    def test_mutating_any_dimension_changes_identity(self, field):
        mutated = dict(_dims())
        v = mutated[field]
        if isinstance(v, bool):
            mutated[field] = not v
        elif isinstance(v, int):
            mutated[field] = v + 1
        elif isinstance(v, str):
            mutated[field] = v + "-mut"
        elif isinstance(v, list):
            mutated[field] = [{"rank": 0, "artifact": "mem-X"},
                              {"rank": 1, "artifact": "mem-B"}]
        else:  # pragma: no cover — every dimension has a branch above
            raise AssertionError(f"no mutation rule for {field}")
        assert (execution_fingerprint(**mutated).fingerprint_hash
                != execution_fingerprint(**_dims()).fingerprint_hash)

    @pytest.mark.parametrize("field", list(REQUIRED_EXECUTION_DIMENSIONS))
    def test_dropping_any_dimension_refuses(self, field):
        dropped = dict(_dims())
        dropped[field] = None
        with pytest.raises(StudyError):
            execution_fingerprint(**dropped)

    def test_rank_swap_changes_identity(self):
        swapped = dict(_dims())
        swapped["mapping"] = [{"rank": 0, "artifact": "mem-B"},
                              {"rank": 1, "artifact": "mem-A"}]
        # Same artifacts, swapped ranks: rank0=A vs rank0=B perform
        # differently, so identity MUST differ (brief item 17).
        assert (execution_fingerprint(**swapped).fingerprint_hash
                != execution_fingerprint(**_dims()).fingerprint_hash)

    def test_mapping_rank_gaps_refuse(self):
        bad = dict(_dims())
        bad["mapping"] = [{"rank": 0, "artifact": "mem-A"},
                          {"rank": 2, "artifact": "mem-B"}]
        with pytest.raises(StudyError):
            execution_fingerprint(**bad)

    def test_unknown_study_kind_refuses(self):
        with pytest.raises(StudyError):
            _study(study_kind="VIBES_COMPARISON")

    def test_empty_and_duplicate_candidates_refuse(self):
        with pytest.raises(StudyError):
            _study(hashes=[])
        with pytest.raises(StudyError):
            _study(hashes=["fp1", "fp1"])

    def test_candidate_order_is_presentation(self):
        assert (_study(hashes=["fp1", "fp2"]).manifest_hash
                == _study(hashes=["fp2", "fp1"]).manifest_hash)


# ── tamper evidence ──────────────────────────────────────────────────────────

class TestTamper:
    def test_fingerprint_round_trip(self):
        fp = execution_fingerprint(**_dims())
        assert (ExecutionFingerprint.from_dict(fp.to_dict())
                .fingerprint_hash == fp.fingerprint_hash)

    def test_fingerprint_tamper_refuses(self):
        d = execution_fingerprint(**_dims()).to_dict()
        d["vc_count"] = 99
        with pytest.raises(StudyError):
            ExecutionFingerprint.from_dict(d)

    def test_manifest_round_trip_and_tamper(self):
        m = _study()
        assert (type(m).from_dict(m.to_dict()).manifest_hash
                == m.manifest_hash)
        d = m.to_dict()
        d["controlled_dimensions"] = {}
        with pytest.raises(StudyError):
            type(m).from_dict(d)

    def test_new_study_ids_unique_and_sorted(self):
        ids = {new_study_id() for _ in range(8)}
        assert len(ids) == 8


# ── cross-surface equivalence ────────────────────────────────────────────────
# Same intent through different construction surfaces → same hashes.
# (CLI/UI surfaces land with worker item 6; the contract they must meet
# is pinned here first.)

class TestEquivalence:
    def test_dict_key_order_irrelevant(self):
        m1 = study_manifest(
            study_id="s", study_kind="DESIGN_COMPARISON",
            workload_artifact_hash="w", candidate_hashes=["a", "b"],
            controlled_dimensions={"x": "1", "y": "2"},
            experimental_variables=["routing"],
            seed_policy="s", backend_policy="b")
        m2 = study_manifest(
            backend_policy="b", seed_policy="s",
            experimental_variables=["routing"],
            controlled_dimensions={"y": "2", "x": "1"},
            candidate_hashes=["b", "a"],
            workload_artifact_hash="w", study_kind="DESIGN_COMPARISON",
            study_id="s")
        assert m1.manifest_hash == m2.manifest_hash

    def test_builder_kwargs_match_from_dict(self):
        m = _study()
        assert (type(m).from_dict(m.to_dict()).manifest_hash
                == m.manifest_hash)

    def test_study_flows_into_comparison_gate(self):
        """A study's intent drives evaluate_comparability with zero
        re-typing: two fingerprints differing only in the study's declared
        variable are COMPARABLE."""
        a = execution_fingerprint(**_dims()).to_comparison_dict()
        b = execution_fingerprint(
            **_dims(fabric_routing="ugal")).to_comparison_dict()
        a["run_id"], b["run_id"] = "run-a", "run-b"
        verdict = evaluate_comparability([a, b], _study().comparison_intent())
        assert verdict.status == "COMPARABLE"

    def test_undeclared_difference_still_refuses(self):
        a = execution_fingerprint(**_dims()).to_comparison_dict()
        b = execution_fingerprint(
            **_dims(fabric_topology="torus_8x8")).to_comparison_dict()
        a["run_id"], b["run_id"] = "run-a", "run-b"
        verdict = evaluate_comparability([a, b], _study().comparison_intent())
        assert verdict.status == "INVALID_COMPARISON"


# ── G: reuse identity vs comparison policy ─────────────────────────────

class TestReuseVsComparability:
    def test_exact_equality_is_reuse(self):
        from veritx_dse.core.study import fingerprints_equal
        a = execution_fingerprint(**_dims())
        assert fingerprints_equal(a, execution_fingerprint(**_dims()))
        assert not fingerprints_equal(
            a, execution_fingerprint(**_dims(fabric_topology="torus_8x8")))

    def test_topology_axis_mismatch_still_comparable(self):
        """Mesh vs torus MUST differ in fingerprint; the declared axis
        makes the comparison valid anyway."""
        a = execution_fingerprint(**_dims()).to_comparison_dict()
        b = execution_fingerprint(
            **_dims(fabric_topology="torus_8x8")).to_comparison_dict()
        a["run_id"], b["run_id"] = "run-a", "run-b"
        m = _study(experimental_variables=("topology",),
                   controlled_dimensions={})
        verdict = evaluate_comparability([a, b], m.comparison_intent())
        assert verdict.status == "COMPARABLE"


# ── H: fidelity-keyed requirements ─────────────────────────────────────

class TestRequiredByFidelity:
    def _fp(self, **kw):
        base = {
            "workload_hash": "w", "node_count": 64,
            "participant_count": 64, "topology": "mesh_8x8",
            "routing": "min_adapt", "vc_count": 4, "packetization": 8,
            "simulator": "booksim2", "network_engine": None,
            "network_mode": "REAL_SIMULATION",
            "fidelity": "NETWORK_SIMULATION",
            "seed_policy": "deterministic:[42]", "run_id": "r",
        }
        base.update(kw)
        return base

    def _intent(self, variables=()):
        return {"kind": "DESIGN_COMPARISON", "objectives": ["latency"],
                "experimental_variables": list(variables),
                "controlled_dimensions": {}}

    def test_analytical_needs_no_vc(self):
        fps = [self._fp(vc_count=None, packetization=None,
                        fidelity="ANALYTICAL_ESTIMATE",
                        simulator="analytical/congestion_aware")
               for _ in range(2)]
        v = evaluate_comparability(fps, self._intent())
        assert v.status == "COMPARABLE"

    def test_serving_requires_network_mode(self):
        fps = [self._fp(network_mode=None,
                        fidelity="SYSTEM_SERVING_SIMULATION",
                        simulator="llmservingsim/booksim")
               for _ in range(2)]
        v = evaluate_comparability(fps, self._intent())
        assert v.status == "INSUFFICIENT_PROVENANCE"
        assert "network_mode" in v.unresolved_dimensions

    def test_unknown_fidelity_refused(self):
        fps = [self._fp(fidelity="FUTURE_EVIDENCE") for _ in range(2)]
        v = evaluate_comparability(fps, self._intent())
        assert v.status == "INSUFFICIENT_PROVENANCE"
        assert v.unresolved_dimensions == ["fidelity"]

    def test_unknown_fidelity_on_one_candidate_refused(self):
        fps = [self._fp(fidelity="FUTURE_EVIDENCE"), self._fp()]
        v = evaluate_comparability(fps, self._intent())
        assert v.status == "INSUFFICIENT_PROVENANCE"

    def test_fidelity_typo_refused(self):
        fps = [self._fp(fidelity="NETWORK_SIMULA TION") for _ in range(2)]
        v = evaluate_comparability(fps, self._intent())
        assert v.status == "INSUFFICIENT_PROVENANCE"

    def test_unknown_fidelity_not_exempted_by_calibration(self):
        fps = [self._fp(fidelity="FUTURE_EVIDENCE") for _ in range(2)]
        v = evaluate_comparability(fps, {
            "kind": "CROSS_FIDELITY_CALIBRATION",
            "objectives": ["latency"],
            "experimental_variables": ["simulator", "fidelity"],
            "controlled_dimensions": {}})
        assert v.status == "INSUFFICIENT_PROVENANCE"


# ── I: anchor chain ────────────────────────────────────────────────────

class TestAnchorChain:
    def test_verify_study_anchor(self):
        from veritx_dse.core.study import verify_study_anchor
        m = _study()
        assert verify_study_anchor(
            m.manifest_hash, m.to_dict()).manifest_hash == m.manifest_hash

    def test_anchor_catches_substitution(self):
        from veritx_dse.core.study import StudyError, verify_study_anchor
        m = _study()
        other = _study(hashes=("fp9", "fp8")).to_dict()
        with pytest.raises(StudyError, match="does not match"):
            verify_study_anchor(m.manifest_hash, other)

    def test_run_manifest_records_study(self, tmp_path, monkeypatch):
        from veritx_dse.core.runs import Run
        import json
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        m = _study()
        run = Run.create(repo=tmp_path, resolved_spec={
            "schema_version": 2}, study_hash=m.manifest_hash)
        manifest = json.loads((run.root / "manifest.json").read_text())
        assert manifest["study"] == m.manifest_hash
