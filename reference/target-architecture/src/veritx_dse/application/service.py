from dataclasses import dataclass
from veritx_dse.backend.booksim import render_trace
from veritx_dse.backend.evidence import EvidenceArtifact
from veritx_dse.workload.messages import build_logical_messages
from veritx_dse.workload.traffic import build_physical_traffic
from veritx_dse.verification.conservation import verify_workload_to_traffic
from .results import EvaluationResult


@dataclass(frozen=True)
class CompiledWorkload:
    graph:object
    messages:object
    traffic:object


class VeriTXService:
    def compile(self,graph,*,fabric,mapping):
        messages=build_logical_messages(graph)
        traffic=build_physical_traffic(graph,messages,mapping=mapping,fabric=fabric)
        verify_workload_to_traffic(graph,messages,traffic)
        return CompiledWorkload(graph,messages,traffic)

    def evaluate(self,compiled,*,backend):
        payload=render_trace(compiled.traffic)
        input_id=compiled.traffic.traffic_id()
        raw=backend.evaluate(input_id=input_id,payload=payload)
        counters,parser_version=backend.parse(raw)
        evidence=EvidenceArtifact.build(backend=backend.name,
                                        backend_input_id=input_id,
                                        input_bytes=payload,raw_evidence=raw,
                                        counters=counters,parser_version=parser_version)
        return EvaluationResult(compiled.graph.workload_id(),
                                compiled.messages.message_artifact_id(),
                                input_id,evidence)
