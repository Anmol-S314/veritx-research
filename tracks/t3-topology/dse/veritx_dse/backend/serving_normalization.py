"""Normalized serving evidence — a view over CanonicalServingEvidence.

Serving never goes through the planner path (it has extra semantic
inputs — cluster config, request trace, CertifiedServiceProfile,
instance geometry — that CanonicalEvaluationContext does not carry),
so there is deliberately NO serving adapter registration: registering
one would fake planner coverage for questions only serving evidence
can answer. This module projects the authoritative
``CanonicalServingEvidence`` into the common normalized envelope
instead.

Gates, in order: the evidence must be live
(``assert_live`` — replay-only protocol output never normalizes) and
every instance must have completed work
(``assert_all_instances_served`` — a total request count is not
sufficient evidence). Model fidelity is FULL_SYSTEM_SIMULATION: a
serving run genuinely composes serving, scheduler and the live network.

SERVING_TTFT projects ``RequestMetric.ttft_cycles`` per request;
SERVING_COMPLETION projects ``RequestMetric.completion_cycles`` per
request. Metric identity is ``(key, (("request_id", ...),))`` — never
invented key suffixes. A request with no metric for a question is
absent from that envelope, never zero-filled. TPOT is deliberately
absent: native evidence does not prove it.
"""
from __future__ import annotations

from typing import Any

from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.backend.adapter import ModelFidelity
from veritx_dse.backend.canonical_serving import CanonicalServingEvidence
from veritx_dse.backend.normalized_evidence import (
    MetricValue, NormalizedBackendEvidence,
)

#: names the canonical serving authority in normalized envelopes. Not a
#: planner adapter id and never registered: SERVING_* questions are
#: answered from serving evidence, not the planner path.
SERVING_BACKEND_ID = "CANONICAL_SERVING"

#: a serving run composes serving + scheduler + live network execution
SERVING_MODEL_FIDELITY = ModelFidelity.FULL_SYSTEM_SIMULATION

SERVING_LIMITATIONS = (
    "full-system simulation: serving scheduler composed with live "
    "network execution; per-request cycles are service-level completion "
    "windows, never isolated network transit",
    "collective-tier live execution only: replay-only or partial runs "
    "never normalize",
)

SERVING_QUESTIONS = (
    EvaluationQuestion.SERVING_TTFT,
    EvaluationQuestion.SERVING_COMPLETION,
)


def normalize_serving_evidence(
    evidence: CanonicalServingEvidence,
) -> tuple[NormalizedBackendEvidence, NormalizedBackendEvidence]:
    """Project live, complete serving evidence into TTFT + completion
    envelopes. The native evidence stays authoritative; these are an
    index/view over its per-request metrics."""
    if not isinstance(evidence, CanonicalServingEvidence):
        raise TypeError(
            f"normalize_serving_evidence takes a "
            f"CanonicalServingEvidence, got "
            f"{type(evidence).__name__}")
    # Gate order is the law: liveness first, then completeness. A
    # replay-only run and a partial run both refuse — never a silent
    # subset normalization.
    evidence.assert_live()
    evidence.assert_all_instances_served()
    ttft = _envelope(evidence, EvaluationQuestion.SERVING_TTFT,
                     "ttft_cycles")
    completion = _envelope(evidence, EvaluationQuestion.SERVING_COMPLETION,
                           "completion_cycles")
    return ttft, completion


def _envelope(
    evidence: CanonicalServingEvidence,
    question: EvaluationQuestion,
    metric_key: str,
) -> NormalizedBackendEvidence:
    metrics: list[MetricValue] = []
    for request in evidence.request_metrics:
        value = getattr(request, metric_key)
        if value is None:
            continue  # absent, never zero-filled
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        metrics.append(MetricValue(
            key=metric_key, value=float(value), unit="cycles",
            source_metric_key=metric_key,
            dimensions=(("request_id", request.request_id),)))
    return NormalizedBackendEvidence(
        backend_id=SERVING_BACKEND_ID, question=question,
        model_fidelity=SERVING_MODEL_FIDELITY,
        canonical_parent_ids=(
            evidence.workload_id,
            evidence.service_profile_id,
            evidence.machine_id,
            evidence.namespace_id,
            evidence.serving_binding_id),
        native_evidence_id=evidence.evidence_id(),
        qualification=evidence.execution_mode,
        producer_identity=evidence.astra_binary_sha256,
        metrics=tuple(metrics),
        limitations=SERVING_LIMITATIONS)


def serving_envelopes_to_dicts(
    envelopes: tuple[NormalizedBackendEvidence, ...],
) -> list[dict[str, Any]]:
    """Language-neutral projection of serving envelopes for persistence
    beside the native serving evidence (mirrors AnalysisOutcome.to_dict
    metric rows so readers parse one shape)."""
    return [
        {
            "question": envelope.question.value,
            "backend_id": envelope.backend_id,
            "model_fidelity": envelope.model_fidelity.value,
            "qualification": envelope.qualification,
            "native_evidence_id": envelope.native_evidence_id,
            "producer_identity": envelope.producer_identity,
            "canonical_parent_ids": list(
                envelope.canonical_parent_ids),
            "metrics": [
                {"key": m.key, "value": m.value, "unit": m.unit,
                 "source_metric_key": m.source_metric_key,
                 "dimensions": [list(d) for d in m.dimensions]}
                for m in envelope.metrics],
            "limitations": list(envelope.limitations),
        }
        for envelope in envelopes
    ]


__all__ = [
    "SERVING_BACKEND_ID", "SERVING_LIMITATIONS",
    "SERVING_MODEL_FIDELITY", "SERVING_QUESTIONS",
    "normalize_serving_evidence", "serving_envelopes_to_dicts",
]
