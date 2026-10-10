"""The class-VC-subset BookSim profile is a WITHDRAWN capability.

THE FINDING (measured, not asserted). ``CERTIFIED_BOOKSIM_MESH_DOR_CLASS_VC_V1``
has a real canonical projection predicate and execution handler. The producer
source now accepts the class VC tables, enforces them at injection/transit,
and emits input-VC observations. A copy of the dirty worktree source builds
and completes a two-class diagnostic run with conservation (not qualification).
The checked-in manifest-pinned binary predates these changes and still rejects
the config, so the feature is
not yet qualified for certified use.

The profile remains unqualified for certified use until a clean source build,
manifest verification, and binary re-pin. This module pins only that
remaining binary/manifest gap and live-probes the current pinned producer.

The fail-closed guards this module relies on are NOT weakened:
``validate_mesh_class_vc_observations``, ``verify_trace_conservation`` and the
out-of-range class-index refusals stay exactly as they are (their own tests
live in ``test_support_expansion.py``).
"""
from __future__ import annotations

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
    prepare_booksim_input, select_booksim_profile,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4  # noqa: E402

CLASS_VC_PROFILE = "CERTIFIED_BOOKSIM_MESH_DOR_CLASS_VC_V1"
BINARY = (Path(__file__).resolve().parents[4]
          / "third_party" / "booksim2" / "src" / "booksim")


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


@pytest.fixture(scope="module")
def diagnostic_binary(tmp_path_factory):
    """Build dirty source externally; never replace the manifest-pinned binary."""
    if shutil.which("make") is None or shutil.which("g++") is None:
        pytest.skip("BookSim source build requires make and g++")
    source = BINARY.parent
    build = tmp_path_factory.mktemp("class-vc-build") / "booksim-src"
    shutil.copytree(source, build, ignore=shutil.ignore_patterns(
        "*.o", "*.d", "booksim", "booksim.build-manifest.json",
        "libveritx_embed.a"))
    subprocess.run(["make", "-j2"], cwd=build, check=True,
                   capture_output=True, text=True, timeout=600)
    return build / "booksim"


def test_source_build_enforces_class_vcs_and_emits_observations(tmp_path, diagnostic_binary):
    """The source implementation must work independently of the pinned binary."""
    repo_root = Path(__file__).resolve().parents[4]
    binary = diagnostic_binary
    prepared = prepare_booksim_input(_parents())
    with tempfile.TemporaryDirectory(dir=tmp_path) as run_root:
        record = execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=Path(run_root) / "ok",
            timeout=120, repo_root=repo_root, allow_unqualified_profile=True)
        evidence = record.evidence
        observations = evidence.stats["mesh_class_vc_route_observations"]
        assert set(observations) == {"0", "1"}
        assert evidence.stats["flits_injected"] == prepared.expected_flits
        assert evidence.stats["flits_accepted"] == prepared.expected_flits
        assert evidence.route_observation == "EXECUTED_ROUTE_OBSERVED"

        malformed = replace(prepared, config_text=re.sub(
            r"(?m)^mesh_class_vc_end\s*=.*?;\s*$", "",
            prepared.config_text))
        with pytest.raises(BookSimExecutionError,
                           match="complete DOR_XY class table required"):
            execute_prepared_booksim(
                prepared=malformed, binary=binary,
                run_dir=Path(run_root) / "bad", timeout=120,
                repo_root=repo_root, allow_unqualified_profile=True)


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
    config, replacements = re.subn(rf"(?m)^{field}\s*=.*?;", f"{field} = {value};", prepared.config_text)
    assert replacements == 1
    (tmp_path / "config.cfg").write_text(config)
    (tmp_path / "workload.trace").write_text(prepared.trace_text)
    process = subprocess.run([str(diagnostic_binary), "config.cfg"], cwd=tmp_path,
                             capture_output=True, text=True, timeout=30)
    assert process.returncode != 0
    assert "mesh class VC error: " + reason in process.stdout + process.stderr


def test_source_intersects_stock_request_vcs_instead_of_overriding(tmp_path, diagnostic_binary):
    prepared = prepare_booksim_input(_parents())
    config = prepared.config_text.replace("traffic = trace(workload.trace);", "traffic = uniform;")
    config = config.replace("injection_rate = 0.0;", "injection_rate = 0.1;")
    config += "\nuse_read_write = 1;\nwrite_fraction = 0.0;\nread_request_begin_vc = 0;\nread_request_end_vc = 0;\n"
    (tmp_path / "config.cfg").write_text(config)
    process = subprocess.run([str(diagnostic_binary), "config.cfg"], cwd=tmp_path,
                             capture_output=True, text=True, timeout=30)
    assert process.returncode != 0
    assert "mesh class VC error: illegal VC for class 0" in process.stdout + process.stderr


@pytest.mark.parametrize("class_id", [-1, 2])
@pytest.mark.parametrize("manager", ["latency", "trace"])
def test_source_refuses_foreign_trace_class_ids(tmp_path, diagnostic_binary, class_id, manager):
    prepared = prepare_booksim_input(_parents())
    config = prepared.config_text
    if manager == "trace":
        config = config.replace("sim_type = latency;", "sim_type = trace;")
        config = config.replace("traffic = trace(workload.trace);", "traffic = uniform;")
        config += "\ntrace_file = workload.trace;\n"
    (tmp_path / "config.cfg").write_text(config)
    (tmp_path / "workload.trace").write_text(f"0 0 {class_id} 1 8\n")
    process = subprocess.run([str(diagnostic_binary), "config.cfg"], cwd=tmp_path,
                             capture_output=True, text=True, timeout=30)
    assert process.returncode != 0
    assert "Trace traffic class outside configured class range" in process.stdout + process.stderr


def test_withdrawal_names_the_owner_stage_and_the_missing_obligation():
    """The refusal is TYPED: it names who owns the fix and exactly what the
    fix is, so it cannot be confused with an unregistered-profile gap."""
    assert qualification_of(CLASS_VC_PROFILE).state == "NOT_QUALIFIED"
    assert CLASS_VC_PROFILE in WITHDRAWN_CAPABILITY_OBLIGATIONS
    reason = withdrawn_capability_reason(CLASS_VC_PROFILE)
    assert reason is not None
    assert "WITHDRAWN capability" in reason
    assert "Owner stage:" in reason and "Missing obligation:" in reason
    # Owner stage = the manifest-pinned BookSim producer binary.
    assert "BookSim fork producer" in reason
    assert "third_party/booksim2" in reason
    assert "routefunc.cpp" in reason
    # Exact missing obligation = the two producer-side halves.
    assert "mesh_class_vc_begin" in reason and "mesh_class_vc_end" in reason
    assert "VeritX: mesh route class" in reason
    assert "currently manifest-pinned binary" in reason
    assert "clean source tree" in reason
    # A genuinely unregistered profile keeps the generic gap text.
    assert withdrawn_capability_reason("NO_SUCH_PROFILE") is None


def test_evaluate_qualification_refuses_and_names_the_withdrawal():
    """The remaining gap is the pinned binary, not the projection: the
    canonical predicate accepts and prepares this design."""
    parents = _parents()
    profile = select_booksim_profile(parents)
    assert profile.profile_id == CLASS_VC_PROFILE
    # The canonical projection predicate is real and accepts these parents.
    prepared = prepare_booksim_input(parents)
    assert prepared.profile_id == CLASS_VC_PROFILE
    qualified, authority = evaluate_qualification(profile, parents)
    assert qualified is False
    assert "WITHDRAWN capability" in authority
    assert "third_party/booksim2" in authority
    assert "mesh_class_vc_begin" in authority


def test_assessment_reports_the_named_withdrawal_as_blocked():
    context = build_evaluation_context(FabricCompiler().compile(
        CompileRequestV4.from_dict(_request_doc())))
    assessment = BookSimAdapter().assess(
        context, EvaluationQuestion.NETWORK_COMPLETION)
    assert assessment.readiness.value == "BLOCKED"
    assert "WITHDRAWN capability" in assessment.reason
    assert "mesh_class_vc_begin" in assessment.reason


def test_pinned_producer_cannot_parse_the_class_vc_config():
    """LIVE: the pinned producer itself refuses the class-VC config.

    This is the evidence that the bounded slice cannot qualify the profile.
    The binary is first proven manifest-pinned and clean, so the refusal is
    not an artifact of a dirty/unattributed tree; the config is then executed
    diagnostically and the producer's own parser refusal is asserted.
    Environment skips (never xfails) only when no binary or no reusable
    producer is available.
    """
    if not BINARY.is_file():
        pytest.skip("no BookSim binary in this worktree")

    from veritx_dse.backend.booksim_execution import (
        BookSimExecutionError, execute_prepared_booksim,
    )
    from veritx_dse.backend.producer import (
        ProducerError, assert_pinned_producer, resolve_producer_identity,
    )

    repo_root = Path(__file__).resolve().parents[4]
    # Prove SEPARATELY that the binary is the manifest-pinned, clean producer,
    # so the refusal below is not an artifact of a dirty/unattributed tree.
    # (A diagnostic run cannot also demand pinning: the execution guard treats
    # "unqualified + pinned" as a contradiction, by construction.)
    try:
        producer = resolve_producer_identity(BINARY, repo_root=repo_root)
        assert_pinned_producer(producer)
    except ProducerError as exc:
        pytest.skip(f"no reusable pinned producer available: {exc}")

    parents = _parents()
    assert select_booksim_profile(parents).profile_id == CLASS_VC_PROFILE
    prepared = prepare_booksim_input(parents)

    with tempfile.TemporaryDirectory() as run_root:
        try:
            execute_prepared_booksim(
                prepared=prepared, binary=BINARY,
                run_dir=Path(run_root) / "run", timeout=300,
                repo_root=repo_root,
                allow_unqualified_profile=True)
        except BookSimExecutionError as exc:
            reason = str(exc)
            assert "Unknown string field: mesh_class_vc_begin" in reason, (
                "the pinned producer did not refuse the class-VC config with "
                f"the expected parse error: {reason}")
            return
    pytest.fail(
        "the manifest-pinned producer ACCEPTED the class-VC config; refresh "
        "the producer qualification evidence and remove this stale withdrawal "
        "pin")
