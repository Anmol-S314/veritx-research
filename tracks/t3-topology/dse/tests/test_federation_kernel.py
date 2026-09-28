"""FEDERATION COMMIT 10 — the federated execution kernel.

The acceptance test: ONE canonical design, BOTH backends, planned
through the registry, executed through their adapters, every identity
bound, no cross-backend numeric equivalence ever claimed.

BookSim's live execution requires a pinned producer (a dirty worktree
skips — honestly); ASTRA's live execution requires the built
AstraSim_BookSim2 binary. The plan-level assertions run on ANY tree:
the kernel's structure does not depend on local executables.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from test_backend_astra_machine import BUILT_FROM_SOURCE  # noqa: E402

from veritx_dse.application.evaluation_context import (  # noqa: E402
    build_evaluation_context,
)
from veritx_dse.application.evaluation_plan import EvaluationPlanner  # noqa: E402
from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.backend.adapter import (  # noqa: E402
    BackendReadiness, ModelFidelity,
)
from veritx_dse.backend.astra_adapter import Astra2Adapter  # noqa: E402
from veritx_dse.backend.astra_namespace import (  # noqa: E402
    stage_endpoint_workload,
)
from veritx_dse.backend.astra_execution import (  # noqa: E402
    execute_astra_machine,
)
from veritx_dse.backend.producer import (  # noqa: E402
    ProducerError, resolve_producer_identity,
)
from veritx_dse.backend.registry import default_backend_registry  # noqa: E402
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.product.service import parse_request_doc  # noqa: E402

DENSE = REPO / "tracks/t3-topology/examples/llama_dense_64tiles-v3.json"

_DIRTY = "producer tree is DIRTY"


def _context():
    compilation = FabricCompiler().compile(
        parse_request_doc(__import__("json").loads(
            DENSE.read_text(encoding="utf-8"))))
    assert compilation.status == "COMPILED"
    return build_evaluation_context(compilation)


# ── the plan: one design, both backends, deterministic rows ──────────

def test_plan_routes_questions_across_the_federation():
    context = _context()
    plan = EvaluationPlanner().plan(
        context,
        (EvaluationQuestion.NETWORK_COMPLETION,
         EvaluationQuestion.SYSTEM_MAKESPAN,
         EvaluationQuestion.PER_RANK_COMPLETION),
        default_backend_registry())

    assert plan.design_hash == context.design_hash
    rf_hash = context.bundle.resolved_fabric.resolved_fabric_hash
    rf_hash = rf_hash() if callable(rf_hash) else rf_hash
    assert plan.resolved_fabric_hash == rf_hash
    rows = {row.question: row for row in plan.analyses}
    network = rows[EvaluationQuestion.NETWORK_COMPLETION]
    assert network.backend_id == "BOOKSIM_STANDALONE"
    # fidelity is named ONLY for READY rows: on a dirty worktree the
    # producer is unpinned, the row is BLOCKED, and a fidelity claim
    # would advertise a model that produced nothing (the planner's law).
    if network.readiness is BackendReadiness.READY:
        assert network.fidelity is ModelFidelity.NETWORK_PACKET_SIMULATION
    else:
        assert network.fidelity is None
        assert network.reason is not None
    for question in (EvaluationQuestion.SYSTEM_MAKESPAN,
                     EvaluationQuestion.PER_RANK_COMPLETION):
        row = rows[question]
        assert row.backend_id == "ASTRA2_EMBEDDED_BOOKSIM"
        if row.readiness is BackendReadiness.READY:
            assert row.fidelity is ModelFidelity.SYSTEM_SIMULATION
    # different fidelity labels for different model kinds — never two
    # names for one number
    if network.fidelity is not None and \
            rows[EvaluationQuestion.SYSTEM_MAKESPAN].fidelity is not None:
        assert network.fidelity is not \
            rows[EvaluationQuestion.SYSTEM_MAKESPAN].fidelity


def test_plan_is_deterministic_across_registries():
    """Installation order cannot alter the plan."""
    context = _context()
    questions = (EvaluationQuestion.NETWORK_COMPLETION,
                 EvaluationQuestion.SYSTEM_MAKESPAN)
    first = EvaluationPlanner().plan(context, questions,
                                     default_backend_registry())
    from veritx_dse.backend.registry import BackendRegistry
    swapped = BackendRegistry((Astra2Adapter(),))
    from veritx_dse.backend.booksim_adapter import BookSimAdapter
    swapped.register(BookSimAdapter())
    second = EvaluationPlanner().plan(context, questions, swapped)
    assert [(r.backend_id, r.readiness) for r in first.analyses] == \
        [(r.backend_id, r.readiness) for r in second.analyses]


def test_canonical_parents_are_shared_across_backends():
    """Both adapters must project the SAME design/fabric/workload — no
    backend owns a private view of the canonical context."""
    context = _context()
    registry = default_backend_registry()
    for adapter in registry.adapters():
        assessment = adapter.assess(
            context, EvaluationQuestion.SYSTEM_MAKESPAN
            if adapter.backend_id == "ASTRA2_EMBEDDED_BOOKSIM"
            else EvaluationQuestion.NETWORK_COMPLETION)
        if assessment.support is not None and assessment.reason is None \
                or assessment.readiness is BackendReadiness.READY:
            assert "design" in assessment.required_parents
            assert "resolved_fabric" in assessment.required_parents
            assert "workload" in assessment.required_parents


# ── ASTRA live execution through the adapter ─────────────────────────

_requires_astra = pytest.mark.skipif(
    not BUILT_FROM_SOURCE.is_file(),
    reason="no AstraSim_BookSim2 binary built in this worktree")


@_requires_astra
def test_astra_actually_spawns_and_authenticates(tmp_path):
    """The real binary runs the adapter's prepared machine; the runtime
    evidence is the backend-native authority, identity-bound to the
    canonical parents."""
    from veritx_dse.backend.adapter import PreparedExecution

    context = _context()
    adapter = Astra2Adapter()
    prepared = adapter.prepare(context,
                               EvaluationQuestion.SYSTEM_MAKESPAN)
    native = prepared.native_prepared
    run = tmp_path / "run"
    run.mkdir(parents=True)
    # step 1: the canonical per-rank Chakra ETs (rank-indexed); step 2:
    # the namespace adapter translates them to endpoint-indexed files
    canonical = tmp_path / "canonical"
    native.workload_projection.write_chakra(
        directory=canonical, stem="workload")
    staged = stage_endpoint_workload(
        workload=native.workload_projection,
        namespace=native.namespace,
        source_directory=canonical,
        target_directory=run, stem="workload")
    evidence = execute_astra_machine(
        machine=native.machine,
        binary=str(BUILT_FROM_SOURCE), run_dir=run,
        workload_configuration=staged.base, timeout_s=900,
        namespace=native.namespace, booksim_source_root=REPO)

    assert evidence.status == "EXECUTED"
    # every identity is the canonical chain's, not a local invention
    assert evidence.machine_id == native.machine_id
    assert evidence.workload_projection_id == native.workload_projection_id
    assert evidence.prepared_id == native.prepared_id
    assert evidence.rank_to_endpoint == native.rank_to_endpoint
    assert evidence.aggregate_cycles > 0


# ── BookSim live execution through the adapter ───────────────────────

def test_booksim_actually_spawns_and_authenticates(tmp_path):
    from veritx_dse.application.evaluation_question import (
        EvaluationQuestion as _Q,
    )
    from veritx_dse.backend.adapter import PreparedExecution as _P
    from veritx_dse.backend.booksim_adapter import BookSimAdapter
    from veritx_dse.backend.producer import (
        ProducerError, assert_pinned_producer,
    )

    context = _context()
    lowered_class = context.unified_traffic_class
    adapter = BookSimAdapter()
    prep = adapter.prepare(context, _Q.NETWORK_COMPLETION,
                           traffic_class=lowered_class)
    binary = REPO / "third_party/booksim2/src/booksim"
    try:
        producer = resolve_producer_identity(binary, repo_root=REPO)
        assert_pinned_producer(producer)
    except ProducerError as exc:
        pytest.skip(f"no pinned BookSim producer in this worktree: {exc}")

    exec_prepared = prep  # prepare() already returns the federation seam
    native = exec_prepared.native_prepared
    result = adapter.execute(exec_prepared, SimpleNamespace(
        binary=binary, repo_root=REPO, run_dir=tmp_path / "eval",
        timeout=600, seed=0))

    record = result.record
    evidence = record.evidence
    # Conservation counters live in the native stats mapping (the
    # evidence dataclass carries identities, not counters); the fork
    # emits no "declared" counter — declared truth is the preparation's
    # expected_packets, and the execution gate already proved
    # loaded == injected == delivered == expected. Strict lookups so a
    # backend that stops emitting a counter fails loudly.
    stats = evidence.stats
    expected = native.prepared.expected_packets
    assert stats["loaded_trace_packets"] == expected
    assert stats["injected_trace_packets"] == expected
    assert evidence.binary_sha256 == producer.binary_sha256
    assert evidence.prepared_id == native.realization_digest
    assert evidence.config_sha256 == native.config_hash
    # the producer identity the adapter bound IS the pinned one
    assert result.producer.binary_sha256 == producer.binary_sha256
