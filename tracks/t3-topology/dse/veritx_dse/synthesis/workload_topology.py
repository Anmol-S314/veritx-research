"""veritx_dse.synthesis.workload_topology — workload → explicit topology.

This is the missing bridge between the canonical workload lowering and the
canonical synthesis pipeline:

    CompileRequestV4
      -> lower_compile_workload()
      -> logical message artifact (V2 single-class / V3 multi-class)
      -> SynthesisTrafficMatrix
      -> pad to the synthesis definition's node count
      -> SynthesisDefinition + synthesizer
      -> TopologyCandidate
      -> ExplicitTopologyIntent(graph=TopologyIR)
      -> CompileRequestV4(topology=...)
      -> FabricCompiler.compile()

Nothing here invents traffic, a traffic class, a topology family or an agent
attachment. Each step either uses the canonical authority named above or
refuses with a typed error.

Rationale: docs/decisions/modules/synthesis.md
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.errors import SemanticError
from veritx_dse.model import topology_ir as tir
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import ExplicitTopologyIntent
from veritx_dse.synthesis.candidate import TopologyCandidate
from veritx_dse.synthesis.definition import SynthesisDefinition
from veritx_dse.synthesis.traffic import SynthesisTrafficMatrix
from veritx_dse.workload.intent_lowering import (
    build_multi_class_messages,
    build_single_class_messages,
    lower_compile_workload,
)

class WorkloadTopologyError(ValueError, SemanticError):
    """A workload cannot be bridged to a compilable explicit topology.

Rationale: docs/decisions/modules/synthesis.md
    """

def _require_request(request: Any) -> CompileRequestV4:
    if not isinstance(request, CompileRequestV4):
        raise WorkloadTopologyError(
            "workload topology bridging takes a CompileRequestV4, got "
            f"{type(request).__name__}")
    return request

def _require_definition(definition: Any) -> SynthesisDefinition:
    if not isinstance(definition, SynthesisDefinition):
        raise WorkloadTopologyError(
            "workload topology bridging takes a SynthesisDefinition, got "
            f"{type(definition).__name__}")
    return definition

def traffic_matrix_from_request(
        request: CompileRequestV4, *, unit: str = "bytes",
) -> SynthesisTrafficMatrix:
    """Lower a v4 request and project its logical messages into a matrix.

    The artifact variant is selected from the LOWERED workload's classes:
    more than one class needs the V3 per-operation artifact; one class uses
    the V2 artifact. A class is never guessed or relabelled — a lowering
    that spans classes must be carried losslessly by V3.

Rationale: docs/decisions/modules/synthesis.md
    """
    request = _require_request(request)
    lowered = lower_compile_workload(request)
    if len(lowered.classes) > 1:
        artifact = build_multi_class_messages(lowered)
    else:
        artifact = build_single_class_messages(lowered)
    return SynthesisTrafficMatrix.from_message_artifact(artifact, unit=unit)

def pad_traffic_matrix(
        matrix: SynthesisTrafficMatrix, nodes: int,
) -> SynthesisTrafficMatrix:
    """Embed an NxN matrix in the top-left of an MxM matrix (M >= N).

    The extra nodes carry ZERO demand: padding changes the matrix dimension,
    not the workload's traffic. Padding therefore changes the matrix
    IDENTITY — ``source_artifact_id`` gets a ``#padded-to-M`` suffix, and
    the content hash changes with the addressed dimension — even though
    ``total_demand()`` is preserved. That is deliberate: a padded matrix is
    a different synthesis problem, and two matrices with the same
    traffic_id must have the same content.

    A shrink is refused — dropping rows/columns would silently discard
    participants.

Rationale: docs/decisions/modules/synthesis.md
    """
    if not isinstance(matrix, SynthesisTrafficMatrix):
        raise WorkloadTopologyError(
            f"pad_traffic_matrix takes a SynthesisTrafficMatrix, got "
            f"{type(matrix).__name__}")
    if type(nodes) is not int or nodes < 2:
        raise WorkloadTopologyError(
            f"padding target must be an int >= 2, got {nodes!r}")
    if nodes < matrix.dimension:
        raise WorkloadTopologyError(
            f"cannot pad a {matrix.dimension}-node traffic matrix down to "
            f"{nodes} nodes: padding never shrinks, and dropping rows would "
            "discard participants instead of seating them")
    rows = [[0.0] * nodes for _ in range(nodes)]
    for i in range(matrix.dimension):
        for j in range(matrix.dimension):
            rows[i][j] = matrix.values[i][j]
    return SynthesisTrafficMatrix.from_rows(
        rows,
        source_artifact_id=(
            f"{matrix.source_artifact_id}#padded-to-{nodes}"),
        namespace=matrix.namespace,
        unit=matrix.unit,
        aggregation=matrix.aggregation,
    )

def candidate_to_intent(
        candidate: TopologyCandidate,
        definition: SynthesisDefinition,
) -> ExplicitTopologyIntent:
    """Freeze a succeeded candidate as ordinary explicit topology intent.

    The synthesized graph is not a second topology schema: it becomes the
    SAME ``TopologyIR(kind="custom")`` a hand-authored explicit graph uses,
    with the definition's link specification and min-hop routing.

Rationale: docs/decisions/modules/synthesis.md
    """
    if not isinstance(candidate, TopologyCandidate):
        raise WorkloadTopologyError(
            f"candidate_to_intent takes a TopologyCandidate, got "
            f"{type(candidate).__name__}")
    definition = _require_definition(definition)
    if candidate.status != "SUCCEEDED":
        raise WorkloadTopologyError(
            f"cannot convert a {candidate.status} candidate to topology "
            f"(algorithm={candidate.algorithm!r}, "
            f"producer={candidate.producer_id!r})")
    if candidate.nodes != definition.nodes:
        raise WorkloadTopologyError(
            f"candidate nodes {candidate.nodes} != definition nodes "
            f"{definition.nodes}: the candidate does not describe this "
            "synthesis problem")
    graph = tir.from_dict({
        "name": f"synthesized_{candidate.algorithm}_{definition.nodes}",
        "kind": "custom",
        "nodes": definition.nodes,
        "links": [list(edge) for edge in candidate.links],
        "link_attrs": {
            "bandwidth_GBs": definition.bandwidth_GBs,
            "latency_ns": definition.latency_ns,
        },
        "routing": "min",
    })
    return ExplicitTopologyIntent(graph=graph)

@dataclass(frozen=True)
class SynthesizedTopology:
    """One workload -> matrix -> candidate -> explicit topology -> compile.

    ``request`` is the synthesized request (the base design with its
    topology replaced); ``matrix``, ``candidate`` and ``topology`` retain
    the bridge inputs/outputs so a caller can inspect or reproduce the
    result without re-deriving it.

Rationale: docs/decisions/modules/synthesis.md
    """

    request: CompileRequestV4
    matrix: SynthesisTrafficMatrix
    candidate: TopologyCandidate
    topology: ExplicitTopologyIntent
    compilation: Any

    def to_dict(self) -> dict[str, Any]:
        """JSON-native, deterministic summary of the whole bridge."""
        graph = self.topology.graph
        return {
            "design_hash": self.request.design_hash(),
            "topology": {
                "kind": graph.kind,
                "nodes": graph.nodes,
                "links": [list(edge) for edge in (graph.links or [])],
            },
            "candidate": {
                "algorithm": self.candidate.algorithm,
                "status": self.candidate.status,
                "producer": self.candidate.producer_id,
            },
            "matrix": {
                "traffic_id": self.matrix.traffic_id(),
                "dimension": self.matrix.dimension,
                "total_demand": self.matrix.total_demand(),
            },
            "compilation": {"status": self.compilation.status},
        }

def _default_synthesizer() -> Callable[..., TopologyCandidate]:
    """Resolve ``synthesis.candidate.synthesize`` at call time.

    Late resolution keeps the default replaceable (a test or a future
    engine can monkeypatch the canonical function) while still naming the
    ONE canonical synthesizer as the default.
    """
    from veritx_dse.synthesis import candidate as candidate_module
    return candidate_module.synthesize

def synthesize_request(
        base: CompileRequestV4,
        definition: SynthesisDefinition,
        *,
        synthesizer: Callable[..., TopologyCandidate] | None = None,
        unit: str = "bytes",
) -> SynthesizedTopology:
    """Bridge one workload request to a compiled explicit topology.

    The matrix must seat every participant: a definition smaller than the
    lowered traffic dimension is refused before synthesis. A larger
    definition gets zero-demand padding, so the synthesizer always receives
    an exactly ``definition.nodes`` square problem.

    The compiler is the attachment authority. Agent counts are never
    adjusted to make a topology fit; if the compiler refuses the attachment
    (or any other stage), its status/error is surfaced as a
    ``WorkloadTopologyError`` rather than swallowed.

Rationale: docs/decisions/modules/synthesis.md
    """
    base = _require_request(base)
    definition = _require_definition(definition)

    matrix = traffic_matrix_from_request(base, unit=unit)
    if definition.nodes < matrix.dimension:
        raise WorkloadTopologyError(
            f"definition nodes {definition.nodes} < traffic dimension "
            f"{matrix.dimension}: a smaller graph cannot seat every "
            "participant")
    if definition.nodes > matrix.dimension:
        matrix = pad_traffic_matrix(matrix, definition.nodes)

    synth = synthesizer if synthesizer is not None else _default_synthesizer()
    candidate = synth(definition, matrix)
    if not isinstance(candidate, TopologyCandidate):
        raise WorkloadTopologyError(
            f"synthesizer returned {type(candidate).__name__}, expected a "
            "TopologyCandidate")
    if candidate.status != "SUCCEEDED":
        raise WorkloadTopologyError(
            f"synthesis did not produce a topology: status "
            f"{candidate.status!r} (algorithm={candidate.algorithm!r}, "
            f"producer={candidate.producer_id!r})")

    topology = candidate_to_intent(candidate, definition)
    request = replace(base, topology=topology)
    compilation = FabricCompiler().compile(request)
    if compilation.status != "COMPILED" or compilation.bundle is None:
        raise WorkloadTopologyError(
            "compiler refused the synthesized topology: status "
            f"{compilation.status!r} at stage "
            f"{compilation.stopped_at_stage!r}: {compilation.error}")
    return SynthesizedTopology(
        request=request,
        matrix=matrix,
        candidate=candidate,
        topology=topology,
        compilation=compilation,
    )

__all__ = [
    "WorkloadTopologyError",
    "SynthesizedTopology",
    "traffic_matrix_from_request",
    "pad_traffic_matrix",
    "candidate_to_intent",
    "synthesize_request",
]
