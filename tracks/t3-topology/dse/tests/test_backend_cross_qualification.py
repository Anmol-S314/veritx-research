"""Wave B3.8b tests — cross-backend semantic intersection + unsupported domains.

No latency parity here: the contracts are "same exact claim => same
authoritative source" and "cannot represent => explicit, visible loss".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim import (  # noqa: E402
    TRACE, rebuild_bundle, with_channels_replaced,
)
from test_backend_bundle import make_bundle  # noqa: E402
from test_backend_execution_qualification import (  # noqa: E402
    _rebuild_with_route, _vc,
)
from test_fabric_artifact import _with_hbm, build_chain  # noqa: E402

from veritx_dse.backend.analytical import (  # noqa: E402
    AnalyticalLoweringError, lower_analytical_aware,
    lower_analytical_unaware,
)
from veritx_dse.backend.booksim import (  # noqa: E402
    BookSimLoweringError, exact_flit_bytes, lower_booksim_standalone,
)
from veritx_dse.backend.contracts import (  # noqa: E402
    CertificationEffect, RepresentationStatus, SemanticDimension,
)
from veritx_dse.backend.qualification import (  # noqa: E402
    QualificationError, TARGET_SPECIFIC_EXCLUSIONS, qualify_cross_backend,
)
from veritx_dse.backend.serving import lower_serving_booksim  # noqa: E402
from veritx_dse.core.route_artifact import (  # noqa: E402
    ANYNET_MIN_HOPS, DOR_XY,
)

@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def bundle(chain):
    return make_bundle(chain)


def four_targets(bundle):
    n = bundle.attachment.endpoint_count
    return {
        "BOOKSIM_STANDALONE": lower_booksim_standalone(bundle),
        "SERVING_BOOKSIM2": lower_serving_booksim(bundle),
        "SERVING_ANALYTICAL_AWARE": lower_analytical_aware(
            bundle, network_dims=(n,)).config,
        "SERVING_ANALYTICAL_UNAWARE": lower_analytical_unaware(
            bundle, network_dims=(n,)).config,
    }


class TestTargetIdentity:
    """Caller labels cannot misrepresent artifact target identity."""

    def test_swapped_labels_refused(self, bundle):
        arts = four_targets(bundle)
        swapped = {
            "BOOKSIM_STANDALONE": arts["SERVING_BOOKSIM2"],
            "SERVING_BOOKSIM2": arts["BOOKSIM_STANDALONE"],
            "SERVING_ANALYTICAL_AWARE":
                arts["SERVING_ANALYTICAL_AWARE"],
            "SERVING_ANALYTICAL_UNAWARE":
                arts["SERVING_ANALYTICAL_UNAWARE"],
        }
        with pytest.raises(QualificationError,
                           match="does not match artifact"):
            qualify_cross_backend(swapped)

    def test_arbitrary_labels_refused(self, bundle):
        arts = four_targets(bundle)
        with pytest.raises(QualificationError,
                           match="does not match artifact"):
            qualify_cross_backend({
                "FOO": arts["BOOKSIM_STANDALONE"],
                "BAR": arts["SERVING_BOOKSIM2"],
            })

    def test_duplicate_target_under_alias_refused(self, bundle):
        arts = four_targets(bundle)
        with pytest.raises(QualificationError,
                           match="does not match artifact"):
            qualify_cross_backend({
                "BOOKSIM_STANDALONE": arts["BOOKSIM_STANDALONE"],
                "SERVING_BOOKSIM2": arts["BOOKSIM_STANDALONE"],
            })

    def test_valid_labels_report_artifact_identity(self, bundle):
        arts = four_targets(bundle)
        report = qualify_cross_backend(arts)
        assert set(report.targets) == set(arts)
        for claim in report.authorities:
            assert set(claim.targets) <= set(arts)


class TestSemanticIntersection:
    def test_shared_authority_claims_use_one_source(self, bundle):
        artifacts = four_targets(bundle)
        report = qualify_cross_backend(artifacts)
        assert report.targets == tuple(sorted(artifacts))
        assert "TOPOLOGY_GRAPH" in report.shared_authority_dimensions
        for claim in report.authorities:
            for target in claim.targets:
                row = artifacts[target].binding(claim.dimension)
                assert row.source_identity == claim.source_identity
                assert row.representation_status.value == claim.status
                assert row.supported_domain == claim.supported_domain
            assert claim.supported_domain, claim.dimension

    def test_no_false_equalities_over_all_dimensions(self, bundle):
        artifacts = four_targets(bundle)
        for dim in SemanticDimension:
            exact_sources = {
                name: art.binding(dim).source_identity
                for name, art in artifacts.items()
                if art.binding(dim).representation_status in
                (RepresentationStatus.EXACT,
                 RepresentationStatus.DERIVED_EXACT)}
            assert len(set(exact_sources.values())) <= 1, (dim,
                                                           exact_sources)

    def test_analytical_topology_is_coarsened_not_exact(self, bundle):
        artifacts = four_targets(bundle)
        for target in ("SERVING_ANALYTICAL_AWARE",
                       "SERVING_ANALYTICAL_UNAWARE"):
            row = artifacts[target].binding(
                SemanticDimension.TOPOLOGY_GRAPH)
            assert row.representation_status is \
                RepresentationStatus.COARSENED
            assert row.certification_effect is \
                CertificationEffect.FIDELITY_DOWNGRADE
            assert row.reason and "shape" in row.reason
        report = qualify_cross_backend(artifacts)
        claim = next(c for c in report.authorities
                     if c.dimension is SemanticDimension.TOPOLOGY_GRAPH)
        assert claim.targets == ("BOOKSIM_STANDALONE", "SERVING_BOOKSIM2")

    def test_dims_are_policy_not_graph_proof(self, bundle):
        from veritx_dse.backend.analytical import (  # noqa: PLC0415
            lower_analytical_unaware,
        )
        flat = lower_analytical_unaware(bundle, network_dims=(4,)).config
        grid = lower_analytical_unaware(bundle, network_dims=(2, 2)).config
        assert flat.backend_config_hash() != grid.backend_config_hash()
        for art in (flat, grid):
            assert art.binding(SemanticDimension.TOPOLOGY_GRAPH) \
                .representation_status is RepresentationStatus.COARSENED

    def test_broken_projection_is_refused_even_with_same_authority(
            self, bundle):
        from dataclasses import replace  # noqa: PLC0415
        artifacts = four_targets(bundle)
        serving = artifacts["SERVING_BOOKSIM2"]
        tampered_params = dict(serving.normalized_parameters)
        tampered_params["num_vcs"] = 99
        tampered = replace(
            serving, artifact_hash="",
            normalized_parameters=tuple(sorted(tampered_params.items())))
        # The bindings (and therefore the claimed authority) are unchanged;
        # only the realization is broken.
        assert tampered.binding(SemanticDimension.VC_COUNT).source_identity \
            == serving.binding(SemanticDimension.VC_COUNT).source_identity
        artifacts["SERVING_BOOKSIM2"] = tampered
        with pytest.raises(QualificationError,
                           match="realization differs"):
            qualify_cross_backend(artifacts)

    @pytest.mark.parametrize("field,value", [
        ("speculative", 1),
        ("arb_type", "pim"),
        ("router", "event"),
        ("noq", 1),
        ("vc_busy_when_full", 1),
    ])
    def test_backend_profile_drift_is_refused(self, bundle, field, value):
        from dataclasses import replace  # noqa: PLC0415
        artifacts = four_targets(bundle)
        serving = artifacts["SERVING_BOOKSIM2"]
        assert field in dict(serving.normalized_parameters)
        params = dict(serving.normalized_parameters)
        params[field] = value
        artifacts["SERVING_BOOKSIM2"] = replace(
            serving, artifact_hash="",
            normalized_parameters=tuple(sorted(params.items())))
        with pytest.raises(QualificationError,
                           match="shared BookSim realization differs"):
            qualify_cross_backend(artifacts)

    def test_permitted_target_differences_still_qualify(self, bundle):
        from dataclasses import replace  # noqa: PLC0415
        artifacts = four_targets(bundle)
        serving = artifacts["SERVING_BOOKSIM2"]
        params = dict(serving.normalized_parameters)
        params["traffic"] = "uniform_different_transport"
        params["sample_period"] = 12345
        artifacts["SERVING_BOOKSIM2"] = replace(
            serving, artifact_hash="",
            normalized_parameters=tuple(sorted(params.items())))
        report = qualify_cross_backend(artifacts)
        comparison = report.realization_for("BOOKSIM_STANDALONE",
                                            "SERVING_BOOKSIM2")
        assert comparison is not None and comparison.equivalent

    def test_target_specific_exclusion_set_is_closed_and_audited(self):
        from veritx_dse.backend.booksim_profile import (  # noqa: PLC0415
            BOOKSIM_SERVING_PROFILE, BOOKSIM_STANDALONE_PROFILE,
        )
        assert set(TARGET_SPECIFIC_EXCLUSIONS) == {
            "traffic", "sample_period", "seed", "routing_dump_file"}
        for field in TARGET_SPECIFIC_EXCLUSIONS:
            assert field in BOOKSIM_STANDALONE_PROFILE.active_names()
            assert field in BOOKSIM_SERVING_PROFILE.active_names()
            assert TARGET_SPECIFIC_EXCLUSIONS[field]

    def test_rendered_shared_fields_agree(self, bundle, tmp_path):
        from test_backend_booksim import TRACE  # noqa: PLC0415
        from veritx_dse.backend.booksim import (  # noqa: PLC0415
            prepare_booksim_standalone,
        )
        from veritx_dse.backend.serving import (  # noqa: PLC0415
            prepare_serving_booksim,
        )
        standalone = prepare_booksim_standalone(
            bundle, workload_trace=TRACE)
        serving = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))

        def values(prepared):
            out = {}
            for line in prepared.rendered.file("config.cfg").decode() \
                    .splitlines():
                key, val = line.split(" = ", 1)
                out[key] = val.rstrip(";")
            return out

        a, b = values(standalone), values(serving)
        shared = (set(a) | set(b)) - set(TARGET_SPECIFIC_EXCLUSIONS)
        differences = {k: (a.get(k), b.get(k)) for k in shared
                       if a.get(k) != b.get(k)}
        assert differences == {}

    def test_disagreements_are_explicit(self, bundle):
        artifacts = four_targets(bundle)
        report = qualify_cross_backend(artifacts)
        assert report.disagreements
        for row in report.disagreements:
            art = artifacts[row.target]
            binding = art.binding(row.dimension)
            assert binding.reason, (row.target, row.dimension)
            if binding.representation_status is not \
                    RepresentationStatus.BACKEND_IRRELEVANT:
                assert binding.certification_effect is not \
                    CertificationEffect.NONE, (row.target, row.dimension)

    def test_targets_share_fabric_identity_but_not_config_hashes(
            self, bundle):
        artifacts = four_targets(bundle)
        report = qualify_cross_backend(artifacts)
        assert report.fabric_hash == bundle.fabric.fabric_hash()
        assert report.resolved_fabric_hash == \
            bundle.resolved_fabric.resolved_fabric_hash()
        assert len({h for _n, h in report.config_hashes}) == 4
        comparison = report.realization_for("BOOKSIM_STANDALONE",
                                            "SERVING_BOOKSIM2")
        assert comparison is not None and comparison.equivalent

    def test_route_realization_disagreement_is_visible(self, bundle):
        artifacts = four_targets(bundle)
        report = qualify_cross_backend(artifacts)
        rows = {r.target: r for r in report.disagreements
                if r.dimension is SemanticDimension.ROUTE_REALIZATION}
        assert rows["SERVING_BOOKSIM2"].effect == "BLOCKS_EXACT_FABRIC"
        assert "ANALYTICAL" in rows["SERVING_ANALYTICAL_AWARE"].target

    def test_foreign_fabric_targets_refused(self, bundle):
        artifacts = four_targets(bundle)
        foreign = four_targets(make_bundle(_with_hbm()))
        mixed = dict(artifacts)
        mixed["SERVING_BOOKSIM2"] = foreign["SERVING_BOOKSIM2"]
        with pytest.raises(QualificationError, match="fabric_hash"):
            qualify_cross_backend(mixed)


# ── unsupported-domain qualification ────────────────────────────────────

class TestUnsupportedDomains:
    def test_heterogeneous_latency_refused(self, chain):
        topo = with_channels_replaced(
            chain.topo, lambda c: c.channel_id == 0, latency_cycles=2)
        with pytest.raises(BookSimLoweringError, match="couples"):
            lower_booksim_standalone(rebuild_bundle(chain, topo=topo))

    def test_non_unit_route_weight_refused(self, chain):
        topo = with_channels_replaced(
            chain.topo, lambda c: c.channel_id == 0, route_weight=3)
        with pytest.raises(BookSimLoweringError, match="route_weight"):
            lower_booksim_standalone(rebuild_bundle(chain, topo=topo))

    def test_parallel_channels_refused(self, chain):
        from dataclasses import replace
        extra = replace(chain.topo.channels[0],
                        channel_id=len(chain.topo.channels))
        topo = replace(chain.topo,
                       channels=chain.topo.channels + (extra,))
        with pytest.raises(BookSimLoweringError, match="parallel"):
            lower_booksim_standalone(rebuild_bundle(chain, topo=topo))

    def test_non_anynet_route_class_refused(self, chain):
        with pytest.raises(BookSimLoweringError, match="ANYNET_MIN_HOPS"):
            lower_booksim_standalone(
                rebuild_bundle(chain, routing_classes=(DOR_XY,)))

    def test_non_byte_exact_flit_width_refused(self):
        from types import SimpleNamespace
        with pytest.raises(BookSimLoweringError, match="byte-exact"):
            exact_flit_bytes(SimpleNamespace(flit_width_bits=65))

    def test_trace_over_packet_cap_refused(self, bundle):
        from veritx_dse.backend.booksim import render_booksim_standalone
        with pytest.raises(BookSimLoweringError, match="exceeds"):
            render_booksim_standalone(
                bundle, lower_booksim_standalone(bundle),
                workload_trace=b"0 0 0 1 99\n")

    def test_aware_refuses_n_dim(self, bundle):
        with pytest.raises(AnalyticalLoweringError, match="1-dim"):
            lower_analytical_aware(bundle, network_dims=(2, 2))

    def test_escape_and_transition_blocks_are_domain_scoped(self, chain):
        escape = lower_booksim_standalone(
            rebuild_bundle(chain, vc=_vc(chain, escape=(0,))))
        transitions = lower_booksim_standalone(
            rebuild_bundle(chain, vc=_vc(chain, transitions=((0, 1), (1, 0)))))
        for art, dim in ((escape, SemanticDimension.ESCAPE_VCS),
                         (transitions, SemanticDimension.VC_TRANSITIONS)):
            row = art.binding(dim)
            assert row.representation_status is \
                RepresentationStatus.UNREPRESENTABLE
            assert row.certification_effect is \
                CertificationEffect.BLOCKS_EXACT_FABRIC
            assert row.supported_domain == ""
            assert not art.exact_fabric_eligible()

    def test_route_dump_transposition_refused(self, chain, bundle):
        from veritx_dse.backend.booksim import (
            BookSimRouteError, compare_route_realization,
        )
        import tempfile
        from pathlib import Path
        config = lower_booksim_standalone(bundle)
        other = lower_booksim_standalone(
            rebuild_bundle(chain, vc=_vc(chain, escape=(0,))))
        with tempfile.TemporaryDirectory() as td:
            dump = Path(td) / "routing.dump"
            # an empty dump has zero coverage -> refuse
            dump.write_text("# nothing\n")
            with pytest.raises(BookSimRouteError, match="coverage"):
                compare_route_realization(bundle, config, dump)
        assert other.backend_config_hash() != config.backend_config_hash()


class TestExecutionQualification:
    """Lossy execution must never present itself as exact certification."""

    def test_baseline_run_is_explicitly_lossy(self, bundle, tmp_path):
        from test_backend_booksim import (  # noqa: PLC0415
            TRACE, make_capturing_runner, prepare_booksim_standalone,
            run_certified_booksim,
        )
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        ev = run_certified_booksim(
            prepared, run_dir=tmp_path, repo_root=tmp_path,
            runner=make_capturing_runner(bundle, prepared.config),
            binary=tmp_path / "fake")
        assert ev.qualification == "EXECUTED_WITH_DECLARED_LOSS"
        assert ev.qualification != "EXECUTED_EXACT"
        assert ev.exact_fabric_eligible is False
        assert ev.to_dict()["qualification"] == \
            "EXECUTED_WITH_DECLARED_LOSS"

    def test_escape_case_runs_but_is_blocked_from_exact(self, chain,
                                                        tmp_path):
        from test_backend_booksim import (  # noqa: PLC0415
            TRACE, make_capturing_runner, prepare_booksim_standalone,
            run_certified_booksim,
        )
        blocked_bundle = rebuild_bundle(chain, vc=_vc(chain, escape=(0,)))
        prepared = prepare_booksim_standalone(
            blocked_bundle, workload_trace=TRACE)
        ev = run_certified_booksim(
            prepared, run_dir=tmp_path, repo_root=tmp_path,
            runner=make_capturing_runner(blocked_bundle, prepared.config),
            binary=tmp_path / "fake")
        assert ev.qualification == "EXECUTED_BLOCKED_FROM_EXACT"
        assert ev.exact_fabric_eligible is False

    def test_unsupported_execution_never_spawns(self, bundle, tmp_path):
        from dataclasses import replace  # noqa: PLC0415
        from veritx_dse.backend.booksim import (  # noqa: PLC0415
            PreparedBackend, bind_booksim_inputs, render_booksim_standalone,
        )
        from veritx_dse.backend.contracts import sha256_bytes  # noqa: PLC0415
        art = lower_booksim_standalone(bundle)
        binds = list(art.semantic_bindings)
        idx = next(i for i, b in enumerate(binds)
                   if b.dimension is SemanticDimension.HEADER_LAYOUT)
        binds[idx] = replace(
            binds[idx],
            representation_status=RepresentationStatus.UNREPRESENTABLE,
            certification_effect=CertificationEffect.UNSUPPORTED_EXECUTION,
            supported_domain="")
        tampered = replace(art, semantic_bindings=tuple(binds),
                           artifact_hash="")
        trace = b"0 0 0 3 2\n10 3 0 0 2\n"
        rendered = render_booksim_standalone(bundle, tampered,
                                             workload_trace=trace)
        manifest = bind_booksim_inputs(
            tampered, rendered, workload_hash=sha256_bytes(trace))
        prepared = PreparedBackend(bundle=bundle, config=tampered,
                                   rendered=rendered, manifest=manifest)
        calls = {"n": 0}

        def never(cmd, cwd, timeout):
            calls["n"] += 1
            raise AssertionError("spawned despite UNSUPPORTED_EXECUTION")

        with pytest.raises(BookSimLoweringError,
                           match="UNSUPPORTED_EXECUTION"):
            from veritx_dse.backend.booksim import (  # noqa: PLC0415
                run_certified_booksim,
            )
            run_certified_booksim(
                prepared, run_dir=tmp_path, repo_root=tmp_path,
                runner=never, binary=tmp_path / "fake")
        assert calls["n"] == 0
