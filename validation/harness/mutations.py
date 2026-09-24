"""Layer 5: negative mutation detection.

A verifier that only passes good simulations is not a demonstrated
verifier. Each mutation deliberately corrupts one thing a real pipeline
could corrupt — a trace byte, a config byte, a binary, evidence bytes, a
claimed completion — and the canonical path MUST refuse it. A mutation
that slips through is a finding, not a warning.
"""
from __future__ import annotations

import dataclasses
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MutationResult:
    name: str
    caught: bool
    expected: str
    detail: str


def _tiny_prepared():
    from validation.harness.fabric import build
    from validation.harness.spec import ExperimentSpec
    root = Path(__file__).resolve().parents[1]
    spec = ExperimentSpec.load(root / "experiments" / "V01-single-p2p-2x2.json")
    return spec, build(spec)


def _expect(fn, exc_types, token: str) -> tuple[bool, str]:
    try:
        fn()
    except exc_types as exc:
        if token and token not in str(exc):
            return False, f"refused for the wrong reason: {exc}"
        return True, f"refused: {str(exc)[:120]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"raised unexpected {type(exc).__name__}: {exc}"
    return False, "NOT REFUSED — the corruption was accepted"


def run_mutations(binary: Path, work_root: Path) -> list[MutationResult]:
    from veritx_dse.backend import evidence as ev
    from veritx_dse.backend import producer as pd
    from veritx_dse.backend.booksim_execution import (
        BookSimExecutionError, execute_prepared_booksim, materialize_prepared,
        parse_booksim_stats,
    )

    results: list[MutationResult] = []
    work_root = Path(work_root)
    spec, built = _tiny_prepared()
    prepared = built.prepared

    # M1 — a window-only run must not be read as a completion measurement
    def m1():
        parse_booksim_stats(
            "Loaded text trace: 5 packets\nTime taken is 10 cycles\n", "")
    results.append(_mutation(
        "M1_window_only_completion", m1,
        (BookSimExecutionError,), "Completion time"))

    # M2 — a completion after the run window is impossible physics
    def m2():
        parse_booksim_stats(
            "Loaded text trace: 5 packets\nTime taken is 10 cycles\n"
            "Completion time is 99 cycles\n", "")
    results.append(_mutation(
        "M2_completion_after_window", m2,
        (BookSimExecutionError,), "exceeds the run window"))

    # M3 — a trace tampered after preparation must not execute
    def m3():
        held = prepared.prepared_id()
        lines = prepared.trace_text.splitlines()
        # a realistic corruption: one extra packet appears in the trace
        tampered = dataclasses.replace(
            prepared, trace_text=prepared.trace_text + lines[0] + "\n")
        execute_prepared_booksim(
            prepared=tampered, binary=binary, run_dir=work_root / "m3",
            timeout=60, expected_prepared_id=held)
    results.append(_mutation(
        "M3_trace_tamper_after_prepare", m3,
        (BookSimExecutionError,), "modified after preparation"))

    # M4 — a config overwritten in a reused run directory must refuse
    def m4():
        run_dir = work_root / "m4"
        materialize_prepared(prepared, run_dir)
        (run_dir / "config.cfg").write_bytes(b"topology = mesh;\n")
        materialize_prepared(prepared, run_dir)
    results.append(_mutation(
        "M4_config_tamper_in_run_dir", m4,
        (BookSimExecutionError,), "different bytes"))

    # M5 — a binary swapped between identification and spawn must refuse
    def m5():
        victim = work_root / "m5-booksim"
        shutil.copy(binary, victim)
        victim.chmod(0o755)
        identity = pd.resolve_producer_identity(victim)
        with victim.open("ab") as handle:
            handle.write(b"corruption")
        pd.recheck_binary_digest(identity)
    results.append(_mutation(
        "M5_binary_swap_after_identification", m5,
        (pd.ProducerError,), "changed between identification"))

    # a genuine executed record for the evidence mutations
    run_dir = work_root / "m-real"
    record = execute_prepared_booksim(
        prepared=prepared, binary=binary, run_dir=run_dir, timeout=60)

    # M6 — a single flipped evidence byte must be detected on read
    def m6():
        path = Path(record.ref.path)
        original = path.read_bytes()
        try:
            corrupted = bytearray(original)
            corrupted[len(corrupted) // 2] ^= 0x01
            path.write_bytes(bytes(corrupted))
            ev.read_verified_evidence(record.ref)
        finally:
            path.write_bytes(original)
    results.append(_mutation(
        "M6_evidence_byte_flip", m6,
        (ev.BackendEvidenceError,), "modified after execution"))

    # M7 — evidence attributed to the wrong producer binary must refuse
    def m7():
        supervised = ev.ExecutionRecord(
            evidence=dataclasses.replace(
                record.evidence,
                transport=ev.EXECUTION_TRANSPORT_SUPERVISED_PROCESS,
                execution_fidelity="QUALIFIED"),
            attempt=record.attempt)
        ev.verify_reusable_record(
            supervised, prepared_id=record.evidence.prepared_id,
            config_sha256=record.evidence.config_sha256,
            trace_sha256=record.evidence.trace_sha256,
            binary_sha256="f" * 64)
    results.append(_mutation(
        "M7_wrong_producer_sha", m7,
        (ev.BackendEvidenceError,), "different BookSim binary"))

    # M8 — evidence transplanted onto a different input must refuse
    def m8():
        from validation.harness.spec import ExperimentSpec
        root = Path(__file__).resolve().parents[1]
        other = ExperimentSpec.load(
            root / "experiments" / "V02-allreduce-4x4.json")
        from validation.harness.fabric import build as build_fn
        other_built = build_fn(other)
        supervised = ev.ExecutionRecord(
            evidence=dataclasses.replace(
                record.evidence,
                transport=ev.EXECUTION_TRANSPORT_SUPERVISED_PROCESS,
                execution_fidelity="QUALIFIED"),
            attempt=record.attempt)
        ev.verify_reusable_record(
            supervised, prepared_id=other_built.prepared.prepared_id(),
            config_sha256=record.evidence.config_sha256,
            trace_sha256=record.evidence.trace_sha256,
            binary_sha256=record.evidence.binary_sha256)
    results.append(_mutation(
        "M8_evidence_transplant", m8,
        (ev.BackendEvidenceError,), "prepared_id"))

    return results


def _mutation(name: str, fn, exc_types, token: str) -> MutationResult:
    caught, detail = _expect(fn, exc_types, token)
    return MutationResult(name=name, caught=caught,
                          expected=f"{exc_types[0].__name__}: {token}",
                          detail=detail)
