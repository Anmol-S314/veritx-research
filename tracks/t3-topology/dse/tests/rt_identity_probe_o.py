"""python3 -O probe: production identity/evidence gates survive -O.

Run as a plain script (never collected by pytest — not named test_*):
builds two same-geometry v3 requests, compiles A, lowers B, and
requires FabricEvaluator to REFUSE the transplant under ``-O``; then
requires the evidence-authentication gate to refuse a
non-authenticating artifact. Prints one canonical JSON verdict and
exits non-zero on any bypass.

Deliberately no ``assert`` statements: ``-O`` strips them, which is
exactly the failure mode this probe exists to catch.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    from veritx_dse.application.errors import ControlPlaneError
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.fabric_evaluator import (
        EvaluationOptions,
        FabricEvaluator,
        _require_evidence_authentic,
    )
    from veritx_dse.core.errors import EvidenceInvalid
    from veritx_dse.model.compile_model import (
        Agent,
        AgentKind,
        CollectiveDimension,
        CollectiveIntent,
        CollectiveKind,
        CompileRequestV3,
        DependencyGraph,
        ModelFamily,
        NocConfig,
        QoSClass,
        RequirementV3,
        TopologyFamily,
        WorkloadV3,
    )

    def request(payload_bytes: int) -> CompileRequestV3:
        return CompileRequestV3(
            workload=WorkloadV3(
                model_family=ModelFamily.DENSE_TRANSFORMER, tp=4, dp=1,
                collectives=(CollectiveIntent(
                    kind=CollectiveKind.ALLREDUCE,
                    dimension=CollectiveDimension.TP,
                    payload_bytes=payload_bytes,
                    traffic_class="tp_collective"),)),
            requirements=(RequirementV3(
                qos_class=QoSClass.LATENCY_CRITICAL,
                traffic_class="tp_collective",
                latency_ceiling_cycles=10 ** 9, binding=True),),
            agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH))

    from veritx_dse.workload.intent_lowering import lower_compile_workload

    req_a, req_b = request(2048), request(4096)
    compilation_a = FabricCompiler().compile(req_a)
    if compilation_a.status != "COMPILED":
        print(json.dumps({"ok": False, "stage": "compile",
                          "error": compilation_a.error}))
        return 1
    lowered_b = lower_compile_workload(req_b)

    transplant_refused = False
    try:
        FabricEvaluator().evaluate(
            compilation_a, lowered_b.graph,
            EvaluationOptions(traffic_class="tp_collective"))
    except ControlPlaneError as exc:
        transplant_refused = (exc.code.value == "INVALID_INTENT"
                              and "transplanted" in str(exc))
    except Exception as exc:  # pragma: no cover - diagnostic only
        print(json.dumps({"ok": False, "stage": "transplant",
                          "error": f"{type(exc).__name__}: {exc}"}))
        return 1

    class _Unverifiable:
        def authenticates(self, **kwargs: object) -> bool:
            return False

    evidence_refused = False
    try:
        _require_evidence_authentic(
            _Unverifiable(), backend_input_sha256="x",
            raw_evidence_sha256="y", stats={})
    except EvidenceInvalid:
        evidence_refused = True

    ok = transplant_refused and evidence_refused
    print(json.dumps({"ok": ok, "transplant_refused": transplant_refused,
                      "evidence_refused": evidence_refused}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
