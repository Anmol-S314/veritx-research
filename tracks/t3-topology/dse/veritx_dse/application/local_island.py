"""Application consumer for the explicit abstract local-island model.

Run: python -m veritx_dse.application.local_island experiment.json
Compilation supplies identities/placement/classes, never timing defaults.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import sys

from veritx_dse.core.artifact import FrozenMap, content_id, canonical_bytes, thaw
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, Refusal, SemanticError
from veritx_dse.model.local_island import PROFILE, LocalIslandContract, IslandOffer, record
from veritx_dse.simulation.local_island import simulate_local_island


@dataclass(frozen=True)
class LocalIslandEvidence:
    data: FrozenMap

    def artifact_id(self):
        return content_id("veritx/LocalIslandEvidence/v1", self.data)

    def to_dict(self):
        return {**thaw(self.data), "artifact_id": self.artifact_id()}

    @classmethod
    def from_dict(cls, doc, *, compilation, contract, offers, horizon_cycles):
        expected = execute_local_island(compilation, contract, offers, horizon_cycles)
        if canonical_bytes(doc) != canonical_bytes(expected.to_dict()):
            raise EvidenceInvalid("local island evidence differs from parent-recomputed execution")
        return expected


def execute_local_island(compilation, contract, offers, horizon_cycles):
    from veritx_dse.application.fabric_compiler import Compilation
    if not isinstance(compilation, Compilation) or compilation.status != "COMPILED":
        raise InvalidInput("local island model requires a successful Compilation")
    if type(contract) is not LocalIslandContract:
        raise InvalidInput("explicit abstract local island contract is required")
    root = compilation.compiled_system
    root.revalidate()
    bundle = root.fabric
    contract.validate_against(bundle.topology, bundle.attachment,
                              dict(bundle.vc_assignment.traffic_class_to_vcs))
    execution = simulate_local_island(contract, offers, horizon_cycles)
    # Canonical sorting makes replay independent of transport list order.
    trace = [o.to_dict() for o in sorted(offers, key=lambda o: (o.arrival_cycle, o.offer_id))]
    return LocalIslandEvidence(FrozenMap({
        "type": "veritx/LocalIslandEvidence", "schema_version": 1, "profile": PROFILE,
        "design_hash": root.request.design_hash(), "system_hash": root.system_hash(),
        "contract_id": contract.artifact_id(), "contract": contract.to_dict(),
        "trace_id": content_id("veritx/LocalIslandTrace/v1", trace), "offers": trace,
        "scope": {"timing": "ABSTRACT_LOCAL_ATTACH_ONLY", "native_srota_equivalent": False,
                  "booksim_qualified": False, "physical_timing": False, "signoff_verified": False,
                  "full_fabric": False, "shared_side_buffer": False, "telemetry": False},
        "execution": execution,
    }))


def evaluate_experiment(doc):
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.application.fabric_compiler import FabricCompiler
    record(doc, {"design", "contract", "offers", "horizon_cycles"}, "local island experiment")
    if type(doc["offers"]) is not list:
        raise InvalidInput("offers must be a list")
    compilation = FabricCompiler().compile(CompileRequestV4.from_dict(doc["design"]))
    return execute_local_island(compilation, LocalIslandContract.from_dict(doc["contract"]),
                                tuple(IslandOffer.from_dict(o) for o in doc["offers"]), doc["horizon_cycles"])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit("usage: python -m veritx_dse.application.local_island experiment.json")
    try:
        evidence = evaluate_experiment(json.loads(Path(argv[0]).read_text()))
    except (Refusal, SemanticError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "REFUSED", "profile": PROFILE, "reason": str(exc)}))
        raise SystemExit(1) from None
    print(json.dumps(evidence.to_dict(), sort_keys=True, indent=2))
    if evidence.data["execution"]["status"] != "COMPLETE":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
