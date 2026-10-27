"""The per-class-VC mesh BookSim profile is QUALIFIED.

THE EVIDENCE (measured, not asserted). ``CERTIFIED_BOOKSIM_MESH_DOR_CLASS_VC_V1``
has a canonical projection predicate, an execution handler, and a clean
manifest-pinned producer that accepts and enforces the per-class VC tables.
The pinned producer executes a two-class canonical design with one disjoint VC
per class, exact per-class input-VC membership observed at native route
computation, and flit conservation. Durable evidence lives in
``docs/product/CLASS-VC-REQUALIFICATION-2026-10.md``.

The source-level diagnostics stay in this module: an independently built copy
of the tracked source proves the enforcement and its fail-closed refusals
without borrowing authority from the pin. The pinned tests prove that the
shipped binary is the qualified producer and that its enforcement path is
live. Environment skips (never xfails) only when the source toolchain or a
reusable pinned producer is unavailable.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from tools.sweep_intent_knobs import baseline  # noqa: E402
from veritx_dse.application.booksim_qualification_registry import (  # noqa: E402
    WITHDRAWN_CAPABILITY_OBLIGATIONS, evaluate_qualification,
    qualification_of, withdrawn_capability_reason,
)
from veritx_dse.application.evaluation_context import (  # noqa: E402
    build_evaluation_context,
)
from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.backend.booksim_adapter import BookSimAdapter  # noqa: E402
from veritx_dse.backend.booksim_execution import (  # noqa: E402
    BookSimExecutionError, execute_prepared_booksim,
)
from veritx_dse.backend.booksim_projection import (  # noqa: E402
    mesh_class_vc_ranges, prepare_booksim_input, select_booksim_profile,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4  # noqa: E402

CLASS_VC_PROFILE = "CERTIFIED_BOOKSIM_MESH_DOR_CLASS_VC_V1"
BINARY = REPO / "third_party" / "booksim2" / "src" / "booksim"


def _request_doc(two_classes=True, cycles=1):
    doc = baseline()
    for key in ("design_hash", "guardrail_hash"):
        doc.pop(key, None)
    doc["dependencies"] = [
        {"source": f"a{i}", "target": f"b{i}", "kind": "blocking"}
        for i in range(cycles)
    ] + [
        {"source": f"b{i}", "target": f"a{i}", "kind": "blocking"}
        for i in range(cycles)
    ]
    if two_classes:
        first = doc["workload"]["collectives"][0]
        first["traffic_class"] = "a0"
        second = deepcopy(first)
        second["traffic_class"] = "b0"
        doc["workload"]["collectives"].append(second)
    return doc


def _parents():
    compiled = FabricCompiler().compile(
        CompileRequestV4.from_dict(_request_doc()))
    assert compiled.status == "COMPILED", compiled.error
    context = build_evaluation_context(compiled)
    adapter = BookSimAdapter()
    _, physical = adapter._canonical_traffic(
        context, traffic_class=context.unified_traffic_class)
    return adapter._projection_parents(context, physical)


def _pinned_identity_or_skip():
    if not BINARY.is_file():
        pytest.skip("no BookSim binary in this worktree")
    from veritx_dse.backend.producer import (
        ProducerError, assert_pinned_producer, resolve_producer_identity,
    )
    try:
        identity = resolve_producer_identity(BINARY, repo_root=REPO)
        assert_pinned_producer(identity)
    except ProducerError as exc:
        pytest.skip(f"no reusable pinned producer available: {exc}")
    return identity


@pytest.fixture(scope="module")
def diagnostic_binary(tmp_path_factory):
    """Build tracked source externally; never replace the manifest-pinned binary."""
    if shutil.which("make") is None or shutil.which("g++") is None:
        pytest.skip("BookSim source build requires make and g++")
    source = BINARY.parent
    build = tmp_path_factory.mktemp("class-vc-build") / "booksim-src"
    shutil.copytree(source, build, ignore=shutil.ignore_patterns(
        "*.o", "*.d", "booksim", "booksim.build-manifest.json",
        "libveritx_embed.a"))
    # Compiler temporaries follow TMPDIR. Keep them inside the build so a
    # quota-limited global temporary directory cannot fail the build.
    tmp = build / ".build-tmp"
    tmp.mkdir()
    subprocess.run(
        ["make", "-j2"], cwd=build, check=True, capture_output=True,
        text=True, timeout=600, env={**os.environ, "TMPDIR": str(tmp)})
    return build / "booksim"


def test_source_build_enforces_class_vcs_and_emits_observations(
        tmp_path, diagnostic_binary):
    """The source implementation must work independently of the pinned binary."""
    prepared = prepare_booksim_input(_parents())
    ranges = mesh_class_vc_ranges(_parents())
    assert all(start == end for start, end in ranges)
    with tempfile.TemporaryDirectory(dir=tmp_path) as run_root:
        record = execute_prepared_booksim(
            prepared=prepared, binary=diagnostic_binary,
            run_dir=Path(run_root) / "ok", timeout=120, repo_root=REPO,
            allow_unqualified_profile=True)
        evidence = record.evidence
        observations = evidence.stats["mesh_class_vc_route_observations"]
        assert set(observations) == {str(i) for i in range(len(ranges))}
        for index, (start, _end) in enumerate(ranges):
            assert set(observations[str(index)]) == {str(start)}
        assert evidence.stats["flits_injected"] == prepared.expected_flits
        assert evidence.stats["flits_accepted"] == prepared.expected_flits
        assert evidence.route_observation == "EXECUTED_ROUTE_OBSERVED"

        malformed = replace(prepared, config_text=re.sub(
            r"(?m)^mesh_class_vc_end\s*=.*?;\s*$", "",
            prepared.config_text))
        with pytest.raises(BookSimExecutionError,
                           match="complete DOR_XY class table required"):
            execute_prepared_booksim(
                prepared=malformed, binary=diagnostic_binary,
                run_dir=Path(run_root) / "bad", timeout=120,
                repo_root=REPO, allow_unqualified_profile=True)


@pytest.mark.parametrize("field,value,reason", [
    ("mesh_class_vc_begin", "{-1,0}", "invalid range"),
    ("mesh_class_vc_end", "{2,0}", "invalid range"),
    ("mesh_class_vc_end", "{0,0}", "invalid range"),
    ("mesh_class_vc_begin", "{1}", "complete DOR_XY class table required"),
    ("mesh_class_vc_end", "{1,0,0}", "complete DOR_XY class table required"),
    ("topology", "torus", "complete DOR_XY class table required"),
    ("routing_function", "min_adapt", "complete DOR_XY class table required"),
])
def test_source_rejects_invalid_class_tables_and_route_envelopes(
        tmp_path, diagnostic_binary, field, value, reason):
    prepared = prepare_booksim_input(_parents())
    config, replacements = re.subn(
        rf"(?m)^{field}\s*=.*?;", f"{field} = {value};",
        prepared.config_text)
    assert replacements == 1
    (tmp_path / "config.cfg").write_text(config)
    (tmp_path / "workload.trace").write_text(prepared.trace_text)
    process = subprocess.run(
        [str(diagnostic_binary), "config.cfg"], cwd=tmp_path,
        capture_output=True, text=True, timeout=30)
    assert process.returncode != 0
    assert "mesh class VC error: " + reason in process.stdout + process.stderr


def test_source_intersects_stock_request_vcs_instead_of_overriding(
        tmp_path, diagnostic_binary):
    prepared = prepare_booksim_input(_parents())
    config = prepared.config_text.replace(
        "traffic = trace(workload.trace);", "traffic = uniform;")
    config = config.replace("injection_rate = 0.0;", "injection_rate = 0.1;")
    config += ("\nuse_read_write = 1;\nwrite_fraction = 0.0;\n"
               "read_request_begin_vc = 0;\nread_request_end_vc = 0;\n")
    (tmp_path / "config.cfg").write_text(config)
    process = subprocess.run(
        [str(diagnostic_binary), "config.cfg"], cwd=tmp_path,
        capture_output=True, text=True, timeout=30)
    assert process.returncode != 0
    assert "mesh class VC error: illegal VC for class 0" in (
        process.stdout + process.stderr)


@pytest.mark.parametrize("class_id", [-1, 2])
@pytest.mark.parametrize("manager", ["latency", "trace"])
def test_source_refuses_foreign_trace_class_ids(
        tmp_path, diagnostic_binary, class_id, manager):
    prepared = prepare_booksim_input(_parents())
    config = prepared.config_text
    if manager == "trace":
        config = config.replace("sim_type = latency;", "sim_type = trace;")
        config = config.replace(
            "traffic = trace(workload.trace);", "traffic = uniform;")
        config += "\ntrace_file = workload.trace;\n"
    (tmp_path / "config.cfg").write_text(config)
    (tmp_path / "workload.trace").write_text(f"0 0 {class_id} 1 8\n")
    process = subprocess.run(
        [str(diagnostic_binary), "config.cfg"], cwd=tmp_path,
        capture_output=True, text=True, timeout=30)
    assert process.returncode != 0
    assert "Trace traffic class outside configured class range" in (
        process.stdout + process.stderr)


def test_qualification_record_is_qualified_and_withdrawal_is_cleared():
    record = qualification_of(CLASS_VC_PROFILE)
    assert record.is_qualified
    assert not record.unresolved_evidence()
    assert record.projection_semantics_version == \
        "booksim2-fork+mesh-dor-class-vc/v1"
    assert record.lowerer_version == "DORXY-MC/1"
    assert "qualify_native_mesh_dor_class_vcs" in record.qualifier
    assert CLASS_VC_PROFILE not in WITHDRAWN_CAPABILITY_OBLIGATIONS
    assert withdrawn_capability_reason(CLASS_VC_PROFILE) is None


def test_evaluate_qualification_accepts_the_selected_profile():
    """The selected profile, its semantics, and its evidence all line up."""
    parents = _parents()
    profile = select_booksim_profile(parents)
    assert profile.profile_id == CLASS_VC_PROFILE
    prepared = prepare_booksim_input(parents)
    assert prepared.profile_id == CLASS_VC_PROFILE
    record = qualification_of(CLASS_VC_PROFILE)
    assert prepared.semantics_version == record.projection_semantics_version
    assert prepared.lowerer_version == record.lowerer_version
    qualified, authority = evaluate_qualification(profile, parents)
    assert qualified is True
    assert "QUALIFIED" in authority
    assert record.qualifier in authority
    assert "DORXY-MC/1" in authority


def test_assessment_reports_ready_with_pinned_producer():
    _pinned_identity_or_skip()
    context = build_evaluation_context(FabricCompiler().compile(
        CompileRequestV4.from_dict(_request_doc())))
    assessment = BookSimAdapter().assess(
        context, EvaluationQuestion.NETWORK_COMPLETION)
    assert assessment.readiness.value == "READY"
    assert assessment.reason is None


def test_manifest_pinned_producer_executes_class_vcs_with_exact_ranges(
        tmp_path):
    """LIVE: the shipped producer accepts the canonical two-class design.

    The binary is proven manifest-pinned and clean first, then executed with
    the pin required, so the evidence is attributable to the qualified
    producer rather than a dirty diagnostic build.
    """
    identity = _pinned_identity_or_skip()
    parents = _parents()
    profile = select_booksim_profile(parents)
    assert profile.profile_id == CLASS_VC_PROFILE
    prepared = prepare_booksim_input(parents)
    ranges = mesh_class_vc_ranges(parents)
    assert len(ranges) == len(prepared.trace_class_map) == 2
    assert all(start == end for start, end in ranges)
    assert len({start for start, _end in ranges}) == len(ranges)

    record = execute_prepared_booksim(
        prepared=prepared, binary=BINARY, run_dir=tmp_path / "run",
        timeout=300, repo_root=REPO, require_pinned_producer=True)
    evidence = record.evidence
    assert evidence.execution_fidelity == "QUALIFIED"
    assert evidence.producer_source_revision == identity.source_revision
    assert evidence.producer_dirty is False
    assert evidence.route_observation == "EXECUTED_ROUTE_OBSERVED"
    assert evidence.route_dump_sha256 is not None
    assert evidence.stats["flits_injected"] == prepared.expected_flits
    assert evidence.stats["flits_accepted"] == prepared.expected_flits
    by_class = {
        index: {"injected": count, "accepted": count}
        for index, (_name, count) in enumerate(
            prepared.expected_flits_by_class)
    }
    assert evidence.stats["flits_by_class"] == by_class

    observations = evidence.stats["mesh_class_vc_route_observations"]
    assert set(observations) == {str(i) for i in range(len(ranges))}
    for index, (start, _end) in enumerate(ranges):
        assert set(observations[str(index)]) == {str(start)}
        assert sum(observations[str(index)].values()) > 0
    assert evidence.stats["completion_cycles"] > 0
    assert (tmp_path / "run" / "routing.dump").is_file()


def test_manifest_pinned_producer_refuses_a_stock_vc_conflict(tmp_path):
    """LIVE: the shipped binary enforces the per-class range at injection.

    This is a deliberate diagnostic config, not a canonical prepared input:
    a stock read-request VC of 0 contradicts class 0's certified VC 1, so the
    producer must refuse rather than silently widen the class range.
    """
    _pinned_identity_or_skip()
    prepared = prepare_booksim_input(_parents())
    config = prepared.config_text.replace(
        "traffic = trace(workload.trace);", "traffic = uniform;")
    config = config.replace("injection_rate = 0.0;", "injection_rate = 0.1;")
    config += ("\nuse_read_write = 1;\nwrite_fraction = 0.0;\n"
               "read_request_begin_vc = 0;\nread_request_end_vc = 0;\n")
    (tmp_path / "config.cfg").write_text(config)
    process = subprocess.run(
        [str(BINARY), "config.cfg"], cwd=tmp_path,
        capture_output=True, text=True, timeout=60)
    assert process.returncode != 0
    assert "mesh class VC error: illegal VC for class 0" in (
        process.stdout + process.stderr)
