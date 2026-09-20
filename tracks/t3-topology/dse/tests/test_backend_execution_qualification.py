"""Wave B3.7f — adversarial mutation/tamper/execution qualification.

Proves the B3.7 architecture is actually on the execution path and that
semantic mutations cannot pass silently:
  * every semantic mutation changes backend identity or refuses;
  * non-semantic path/formatting changes never change identity;
  * every tamper shape fails closed;
  * the certified path does not use the legacy config builder;
  * at least one REAL BookSim run proves the artifact executes.
"""
from __future__ import annotations

import copy
import sys
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim import (  # noqa: E402
    TRACE, make_capturing_runner, rebuild_bundle,
)
from test_backend_bundle import make_bundle  # noqa: E402
from test_fabric_artifact import _with_hbm, build_chain  # noqa: E402

from veritx_dse.backend.booksim import (
    _run_qualified_booksim_with_runner_for_test,  # noqa: E402
    BookSimLoweringError, prepare_booksim_standalone, run_certified_booksim,
    lower_booksim_standalone,
)
from veritx_dse.backend.contracts import (  # noqa: E402
    BackendConfigArtifact, BackendConfigError, BackendInputError,
    BackendInputManifest, BackendTarget, CertificationEffect,
    RepresentationStatus, SemanticDimension,
)
from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS, RouteArtifact  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
    derive_vc_assignment_artifact,
)
from veritx_dse.model.packet_format import derive_packet_format  # noqa: E402
from veritx_dse.model.resolved_route import derive_resolved_route  # noqa: E402
from veritx_dse.model.router_behavior import (  # noqa: E402
    AllocatorPolicy, derive_router_behavior,
)
from veritx_dse.model.vc_assignment import make_vc_assignment_artifact  # noqa: E402


@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def bundle(chain):
    return make_bundle(chain)


@pytest.fixture(scope="module")
def base_hash(bundle):
    return lower_booksim_standalone(bundle).backend_config_hash()


def _rebuild_with_route(chain, mutate_entries):
    """Coherent rebuild with one RouteArtifact entry changed."""
    entries = dict(chain.rr.entries)
    mutate_entries(entries)
    rr = RouteArtifact(schema_version=2, name=chain.rr.name,
                       topology_hash=chain.rr.topology_hash,
                       routing_classes=chain.rr.routing_classes,
                       entries=entries)
    rr.validate_against(chain.topo)
    rra = derive_resolved_route(chain.topo, chain.att, rr)
    vc = derive_vc_assignment_artifact(chain.cr, rra)
    pf = derive_packet_format(topology=chain.topo, attachment=chain.att,
                              vc_assignment=vc)
    rb = derive_router_behavior(vc_assignment=vc)
    return rebuild_bundle(chain, vc=vc, pf=pf, rb=rb, routing_classes=(
        ANYNET_MIN_HOPS,))


def _rebuild_with_route_artifact(chain, rr):
    """Coherent rebuild around a supplied RouteArtifact (e.g. renamed)."""
    rr.validate_against(chain.topo)
    rra = derive_resolved_route(chain.topo, chain.att, rr)
    vc = derive_vc_assignment_artifact(chain.cr, rra)
    pf = derive_packet_format(topology=chain.topo, attachment=chain.att,
                              vc_assignment=vc)
    rb = derive_router_behavior(vc_assignment=vc)
    return rebuild_bundle(chain, vc=vc, pf=pf, rb=rb,
                          routing_classes=(ANYNET_MIN_HOPS,))


def _drop_router_pair(topo, a, b):
    kept = tuple(c for c in topo.channels
                 if {c.src_router, c.dst_router} != {a, b})
    return replace(topo, channels=kept)


def _vc(chain, *, vc_count=2, classes=None, escape=(), transitions=None):
    return make_vc_assignment_artifact(
        resolved_route=chain.rra, vc_count=vc_count,
        traffic_class_to_vcs=classes or {"A": [1], "B": [0]},
        derivation="mutation matrix",
        escape_vcs=escape, allowed_transitions=transitions)


# ── §14.3 semantic mutation matrix ──────────────────────────────────────

MUTATIONS = {
    "topology_edge": lambda chain, b: rebuild_bundle(
        chain, topo=_drop_router_pair(chain.topo, 0, 1)),
    "endpoint_attachment": lambda chain, b: replace(
        b, attachment=make_bundle(_with_hbm()).attachment),
    "channel_width": lambda chain, b: make_bundle(
        build_chain(link_width=128)),
    "channel_latency": lambda chain, b: rebuild_bundle(
        chain, topo=replace(chain.topo, channels=tuple(
            replace(c, latency_cycles=2) if c.channel_id == 0 else c
            for c in chain.topo.channels))),
    "route_realization": lambda chain, b: _rebuild_with_route(
        chain, lambda e: e.__setitem__(
            (ANYNET_MIN_HOPS, 0, 1), e[(ANYNET_MIN_HOPS, 1, 0)])),
    "vc_count": lambda chain, b: rebuild_bundle(
        chain, vc=_vc(chain, vc_count=4,
                      classes={"DEFAULT": [0, 1, 2, 3]})),
    "vc_assignment": lambda chain, b: rebuild_bundle(
        chain, vc=_vc(chain, classes={"A": [0], "B": [1]})),
    "escape_vcs": lambda chain, b: rebuild_bundle(
        chain, vc=_vc(chain, escape=(0,))),
    "buffer_depth": lambda chain, b: rebuild_bundle(
        chain, rb=replace(chain.rb, artifact_hash="",
                          input_buffer_depth_flits_per_vc=16)),
    "allocator": lambda chain, b: rebuild_bundle(
        chain, rb=replace(chain.rb, artifact_hash="",
                          vc_allocator=AllocatorPolicy.ROUND_ROBIN)),
    "credit_latency": lambda chain, b: rebuild_bundle(
        chain, rb=replace(chain.rb, artifact_hash="",
                          credit_return_latency_cycles=4)),
    "routing_delay": lambda chain, b: rebuild_bundle(
        chain, rb=replace(chain.rb, artifact_hash="",
                          route_compute_cycles=3)),
    "speedup": lambda chain, b: rebuild_bundle(
        chain, rb=replace(chain.rb, artifact_hash="",
                          input_speedup=2)),
    "flit_width": lambda chain, b: make_bundle(build_chain(link_width=128)),
    "max_packet_flits": lambda chain, b: rebuild_bundle(
        chain, pf=derive_packet_format(topology=chain.topo,
                                       attachment=chain.att,
                                       vc_assignment=chain.vc,
                                       max_packet_flits=16)),
    "address_decode": lambda chain, b: make_bundle(_with_hbm()),
}


class TestSemanticMutationMatrix:
    def test_every_mutation_changes_identity_or_refuses(self, chain, bundle,
                                                        base_hash):
        observed = {}
        for name, mutate in MUTATIONS.items():
            try:
                mutated = mutate(chain, bundle)
                art = lower_booksim_standalone(mutated)
                observed[name] = ("changed", art.backend_config_hash())
            except (BookSimLoweringError, ValueError) as exc:
                observed[name] = ("refused", str(exc)[:80])
        for name, (verdict, value) in observed.items():
            if verdict == "refused":
                assert value, f"{name}: refusal without a reason"
            else:
                assert value != base_hash, (
                    f"{name}: semantic mutation left backend identity "
                    "unchanged")
        # Every mutation must have produced evidence of change or refusal.
        assert len(observed) == len(MUTATIONS)

    def test_loss_or_status_changes_are_visible(self, chain, bundle):
        escape = lower_booksim_standalone(
            rebuild_bundle(chain, vc=_vc(chain, escape=(0,))))
        assert escape.binding(SemanticDimension.ESCAPE_VCS) \
            .representation_status is RepresentationStatus.UNREPRESENTABLE
        assert escape.binding(SemanticDimension.ESCAPE_VCS) \
            .certification_effect is CertificationEffect.BLOCKS_EXACT_FABRIC
        assert not escape.exact_fabric_eligible()


# ── §14.4 non-semantic mutation matrix ──────────────────────────────────

class TestNonSemanticMutations:
    def test_different_directories_same_identity(self, bundle, tmp_path):
        a = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        b = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        assert a.config.backend_config_hash() \
            == b.config.backend_config_hash()
        assert a.manifest.backend_input_hash() \
            == b.manifest.backend_input_hash()
        # Materialize at two different paths: files hash the same.
        from veritx_dse.backend.booksim import materialize_backend
        materialize_backend(a.rendered, a.manifest, tmp_path / "x")
        materialize_backend(a.rendered, a.manifest, tmp_path / "y")
        assert (tmp_path / "x" / "config.cfg").read_bytes() \
            == (tmp_path / "y" / "config.cfg").read_bytes()

    def test_json_whitespace_and_key_order_do_not_matter(self, bundle):
        import json
        a = lower_booksim_standalone(bundle)
        blob = json.loads(json.dumps(a.to_dict(), indent=3))
        b = BackendConfigArtifact.from_dict(blob)
        assert a.backend_config_hash() == b.backend_config_hash()

    def test_presentation_labels_do_not_matter(self, chain, bundle):
        renamed = RouteArtifact.from_topology(
            chain.topo, name="completely-different-presentation-name",
            routing_classes=(ANYNET_MIN_HOPS,))
        # The route artifact hash excludes presentation...
        assert renamed.artifact_hash == chain.rr.artifact_hash
        # ...and feeding the renamed artifact through a full rebuild keeps
        # backend identity byte-identical.
        assert lower_booksim_standalone(
            _rebuild_with_route_artifact(chain, renamed)) \
            .backend_config_hash() \
            == lower_booksim_standalone(bundle).backend_config_hash()

    def test_workload_content_is_execution_semantic(self, bundle):
        a = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        b = prepare_booksim_standalone(
            bundle, workload_trace=TRACE + b"20 2 0 1 1\n")
        assert a.config.backend_config_hash() \
            == b.config.backend_config_hash()
        assert a.manifest.backend_input_hash() \
            != b.manifest.backend_input_hash()


# ── §14.5 tamper tests ──────────────────────────────────────────────────

class TestTamperMatrix:
    def test_wrong_parent_fabric_hash(self, bundle):
        d = lower_booksim_standalone(bundle).to_dict()
        d["fabric_hash"] = "f" * 64
        with pytest.raises(BackendConfigError, match="does not match"):
            BackendConfigArtifact.from_dict(d)

    def test_stale_resolved_fabric_hash(self, bundle):
        d = lower_booksim_standalone(bundle).to_dict()
        d["resolved_fabric_hash"] = "0" * 64
        with pytest.raises(BackendConfigError, match="does not match"):
            BackendConfigArtifact.from_dict(d)

    def test_tampered_normalized_parameters(self, bundle):
        d = lower_booksim_standalone(bundle).to_dict()
        d["normalized_parameters"]["num_vcs"] = 64
        with pytest.raises(BackendConfigError, match="does not match"):
            BackendConfigArtifact.from_dict(d)

    def test_tampered_semantic_binding(self, bundle):
        d = lower_booksim_standalone(bundle).to_dict()
        d["semantic_bindings"][0]["source_identity"] = "a" * 64
        with pytest.raises(BackendConfigError, match="does not match"):
            BackendConfigArtifact.from_dict(d)

    def test_deleted_binding_refused(self, bundle):
        d = lower_booksim_standalone(bundle).to_dict()
        d["semantic_bindings"] = d["semantic_bindings"][:-1]
        with pytest.raises(BackendConfigError, match="missing dimensions"):
            BackendConfigArtifact.from_dict(d)

    def test_duplicate_binding_refused(self, bundle):
        d = lower_booksim_standalone(bundle).to_dict()
        d["semantic_bindings"].append(copy.deepcopy(
            d["semantic_bindings"][0]))
        with pytest.raises(BackendConfigError, match="exactly once"):
            BackendConfigArtifact.from_dict(d)

    def test_tampered_rendered_input_refused(self, bundle, tmp_path):
        from veritx_dse.backend.booksim import (
            materialize_backend, verify_materialized,
        )
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        materialize_backend(prepared.rendered, prepared.manifest,
                            tmp_path / "backend")
        (tmp_path / "backend" / "workload.trace").write_bytes(
            b"0 0 0 1 8\n")
        with pytest.raises(ValueError, match="modified"):
            verify_materialized(prepared.manifest, tmp_path / "backend")

    def test_wrong_rendered_input_hash_refused(self, bundle):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        d = prepared.manifest.to_dict()
        d["rendered_inputs"][0]["sha256"] = "a" * 64
        with pytest.raises(BackendInputError, match="does not match"):
            BackendInputManifest.from_dict(d)

    def test_unknown_target_refused(self, bundle):
        d = lower_booksim_standalone(bundle).to_dict()
        d["backend_target"] = "ASTRA"
        with pytest.raises(BackendConfigError, match="unknown"):
            BackendConfigArtifact.from_dict(d)

    def test_unknown_schema_refused(self, bundle):
        d = lower_booksim_standalone(bundle).to_dict()
        d["schema_version"] = 99
        with pytest.raises(BackendConfigError, match="schema_version"):
            BackendConfigArtifact.from_dict(d)

    def test_unsupported_locked_semantic_refuses_exact(self, chain):
        escape = lower_booksim_standalone(
            rebuild_bundle(chain, vc=_vc(chain, escape=(0,))))
        assert not escape.exact_fabric_eligible()


# ── §14.2 bypass proof ──────────────────────────────────────────────────

class TestBypassProof:
    def test_certified_path_never_uses_legacy_builder(
            self, bundle, tmp_path, monkeypatch):
        import veritx_dse.simulation.booksim as legacy

        def explode(*args, **kwargs):
            raise AssertionError("legacy build_config was used")

        monkeypatch.setattr(legacy, "build_config", explode)
        monkeypatch.setattr(legacy, "BASE_PARAMS",
                            {"exploded": explode})
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        ev = _run_qualified_booksim_with_runner_for_test(
            prepared, run_dir=tmp_path, repo_root=tmp_path,
            runner=make_capturing_runner(bundle, prepared.config),
            binary=Path("/bin/true"))
        assert ev.route_equivalence == "EXACT"

    def test_renderer_never_reads_legacy_defaults(self, bundle):
        art = lower_booksim_standalone(bundle)
        keys = {k for k, _ in art.normalized_parameters}
        # Legacy BASE_PARAMS keys are all fabricated from artifacts instead.
        assert "num_vcs" in keys and "vc_buf_size" in keys
        assert art.backend_profile == "CERTIFIED_BOOKSIM_ANYNET_V1"


# ── §14.6 real execution ────────────────────────────────────────────────

class TestRealExecution:
    def test_real_booksim_runs_the_lowered_artifact(self, bundle, tmp_path):
        from veritx_dse.core.paths import REPO
        from veritx_dse.simulation.booksim import find_booksim_bin
        try:
            binary = find_booksim_bin(REPO)
        except FileNotFoundError:
            pytest.skip("no runnable BookSim binary")
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        ev = run_certified_booksim(
            prepared, run_dir=tmp_path, repo_root=REPO, timeout=120,
            binary=Path(binary))
        assert ev.exit_status == 0
        assert ev.route_equivalence == "EXACT"
        assert ev.stats["delivered"] == 2
        assert ev.backend_config_hash == prepared.config.backend_config_hash()
        assert ev.backend_input_hash == prepared.manifest.backend_input_hash()
