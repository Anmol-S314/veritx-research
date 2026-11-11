"""Per-class BookSim priority is a DECLARED, executed surface.

The sealed class-VC profile stays ``priority = none``; a workload that scopes
an applicable ``RequirementV3.qos_class`` to every canonical class selects the
distinct priority profile. This module proves three separate facts:

* the projection derives ``class_priority`` from the requirements, in trace
  class order, and binds it into the prepared identity;
* a missing, ambiguous, or uniform QoS declaration selects no priority
  profile (never a fabricated rank);
* the fork actually arbitrates on that vector: swapping the two ranks swaps
  which class wins a shared output. The swap test changes nothing else in the
  config, so the allocator cannot be the explanation.
"""
from __future__ import annotations

import re
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from tools.sweep_intent_knobs import baseline  # noqa: E402
from veritx_dse.application.booksim_qualification_registry import (  # noqa: E402
    EXECUTION_HANDLERS, qualification_of,
)
from veritx_dse.application.evaluation_context import (  # noqa: E402
    build_evaluation_context,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.backend.booksim_adapter import BookSimAdapter  # noqa: E402
from veritx_dse.backend.booksim_execution import (  # noqa: E402
    BookSimExecutionError, execute_prepared_booksim,
    validate_class_priority_config,
)
from veritx_dse.backend.booksim_projection import (  # noqa: E402
    MESH_DOR_CLASS_PRIORITY_PROFILE, MESH_DOR_CLASS_VC_PROFILE,
    SemanticLoss, class_priority_plan, mesh_class_vc_ranges,
    parse_config_values, prepare_booksim_input, select_booksim_profile,
    trace_class_map,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4  # noqa: E402

PRIORITY_PROFILE = "CERTIFIED_BOOKSIM_MESH_DOR_CLASS_VC_PRIORITY_V1"
BINARY = REPO / "third_party" / "booksim2" / "src" / "booksim"


def _request_doc(requirements=None):
    """A two-class mesh request with one disjoint VC per class.

    The dependency cycle is the canonical way this design gets a second VC;
    without it the VC assignment is the single full envelope and the sealed
    class-VC path is not selected at all.
    """
    doc = baseline()
    for key in ("design_hash", "guardrail_hash"):
        doc.pop(key, None)
    doc["dependencies"] = [
        {"source": "a0", "target": "b0", "kind": "blocking"},
        {"source": "b0", "target": "a0", "kind": "blocking"},
    ]
    first = doc["workload"]["collectives"][0]
    first["traffic_class"] = "a0"
    second = deepcopy(first)
    second["traffic_class"] = "b0"
    doc["workload"]["collectives"].append(second)
    doc["requirements"] = list(requirements or ())
    return doc


def _parents(requirements=None):
    doc = _request_doc(requirements)
    compiled = FabricCompiler().compile(CompileRequestV4.from_dict(doc))
    assert compiled.status == "COMPILED", compiled.error
    context = build_evaluation_context(compiled)
    adapter = BookSimAdapter()
    _, physical = adapter._canonical_traffic(
        context, traffic_class=context.unified_traffic_class)
    return adapter._projection_parents(context, physical)


def _qos(*pairs):
    return [
        {"traffic_class": traffic_class, "qos_class": qos}
        for traffic_class, qos in pairs
    ]


def test_priority_is_derived_from_scoped_qos_and_bound_into_identity():
    parents = _parents(_qos(("a0", "latency_critical"), ("b0", "bandwidth")))
    assert trace_class_map(parents.physical_traffic) == ("a0", "b0")
    assert class_priority_plan(parents) == (("a0", 2), ("b0", 1))
    assert mesh_class_vc_ranges(parents) == ((1, 1), (0, 0))

    profile = select_booksim_profile(parents)
    assert profile.profile_id == PRIORITY_PROFILE
    prepared = prepare_booksim_input(parents)
    assert prepared.profile_id == PRIORITY_PROFILE
    assert prepared.priority_class_map == (("a0", 2), ("b0", 1))
    values = parse_config_values(prepared.config_text)
    assert values["priority"] == "class"
    assert values["class_priority"] == "{2,1}"
    assert values["sw_allocator"] == "select"
    assert values["vc_allocator"] == "islip"
    assert values["alloc_iters"] == "1"
    assert values["vc_priority_donation"] == "0"
    assert "priority_class_map" in prepared.identity_dict()


def test_no_requirement_selects_no_priority_profile():
    parents = _parents()
    assert class_priority_plan(parents) is None
    profile = select_booksim_profile(parents)
    assert profile.profile_id == MESH_DOR_CLASS_VC_PROFILE.profile_id
    prepared = prepare_booksim_input(parents)
    values = parse_config_values(prepared.config_text)
    assert values["priority"] == "none"
    assert "class_priority" not in values
    assert "sw_allocator" not in values
    assert prepared.priority_class_map == ()


def test_partial_requirement_selects_no_priority_profile():
    parents = _parents(_qos(("a0", "latency_critical")))
    assert class_priority_plan(parents) is None
    assert select_booksim_profile(parents).profile_id == \
        MESH_DOR_CLASS_VC_PROFILE.profile_id


def test_uniform_qos_selects_no_priority_profile():
    parents = _parents(_qos(("a0", "latency_critical"),
                            ("b0", "latency_critical")))
    assert class_priority_plan(parents) is None
    assert select_booksim_profile(parents).profile_id == \
        MESH_DOR_CLASS_VC_PROFILE.profile_id


def test_conflicting_qos_for_one_class_is_refused():
    parents = _parents(_qos(("a0", "latency_critical"),
                            ("a0", "bandwidth"),
                            ("b0", "bandwidth")))
    with pytest.raises(SemanticLoss, match="conflicting QoS"):
        select_booksim_profile(parents)


def test_execution_refuses_a_swapped_priority_vector():
    prepared = prepare_booksim_input(
        _parents(_qos(("a0", "latency_critical"), ("b0", "bandwidth"))))
    validate_class_priority_config(prepared)
    swapped = replace(prepared,
                      priority_class_map=(("a0", 1), ("b0", 2)))
    with pytest.raises(BookSimExecutionError,
                       match="class_priority does not match"):
        validate_class_priority_config(swapped)


def test_priority_profile_is_registered_with_evidence():
    record = qualification_of(PRIORITY_PROFILE)
    assert record.is_qualified
    assert record.unresolved_evidence() == ()
    assert record.projection_semantics_version == \
        MESH_DOR_CLASS_PRIORITY_PROFILE.semantics_version
    assert record.lowerer_version == "DORXY-MC/1"
    assert record.qualifier == (
        "veritx_dse.backend.booksim_projection:"
        "qualify_native_mesh_dor_class_priority")
    assert EXECUTION_HANDLERS[PRIORITY_PROFILE].endswith(
        ":execute_prepared_booksim")
    assert "ASTRA" in record.scope  # the limitation is stated, not implied


def test_execution_refuses_priority_without_a_priority_allocator():
    """`priority = class` under iSLIP is the dead-config trap this profile
    exists to avoid: iSLIP stores the rank and never compares it."""
    prepared = prepare_booksim_input(
        _parents(_qos(("a0", "latency_critical"), ("b0", "bandwidth"))))
    dead = replace(
        prepared,
        config_text=prepared.config_text.replace(
            "sw_allocator = select;", "sw_allocator = islip;"))
    with pytest.raises(BookSimExecutionError,
                       match="select switch allocator"):
        validate_class_priority_config(dead)


def test_qualified_priority_execution_records_the_declared_plan(tmp_path):
    """The qualified profile executes and the evidence carries the binding."""
    if not BINARY.is_file():
        pytest.skip("no BookSim binary in this worktree")
    prepared = prepare_booksim_input(
        _parents(_qos(("a0", "latency_critical"), ("b0", "bandwidth"))))
    record = execute_prepared_booksim(
        prepared=prepared, binary=BINARY, run_dir=tmp_path / "run",
        timeout=300, repo_root=REPO)
    evidence = record.evidence
    assert evidence.profile_id == PRIORITY_PROFILE
    assert evidence.stats["class_priority_plan"] == {"a0": 2, "b0": 1}
    assert evidence.stats["flits_injected"] == prepared.expected_flits
    assert evidence.stats["flits_accepted"] == prepared.expected_flits
    assert set(evidence.stats["latency_by_class"]) == {0, 1}


def _class_packet_average(stdout: str) -> dict[int, float]:
    found = re.findall(
        r"Traffic class (\d+) ======\nPacket latency average = ([0-9.]+)",
        stdout)
    return {int(cls): float(value) for cls, value in found}


def _run_fork(binary: Path, directory: Path, config: str,
              trace: str) -> str:
    directory.mkdir(parents=True)
    (directory / "config.cfg").write_text(config)
    (directory / "workload.trace").write_text(trace)
    process = subprocess.run(
        [str(binary), "config.cfg"], cwd=directory, capture_output=True,
        text=True, timeout=120)
    assert process.returncode == 0, process.stdout[-1000:] + process.stderr
    return process.stdout


def test_fork_arbitrates_on_the_priority_vector(tmp_path):
    """Swap ONLY the two ranks; the winning class must swap too.

    Both classes send one-flit packets to the same destination. ``src0`` needs
    two hops, ``src1`` injects at the contested router, so their arrival
    timestamps are offset by five cycles to put both requests in the same
    switch cycle. If ``class_priority`` were a dead field, the two runs would
    be byte-identical in their per-class latency.
    """
    if not BINARY.is_file():
        pytest.skip("no BookSim binary in this worktree")
    prepared = prepare_booksim_input(
        _parents(_qos(("a0", "latency_critical"), ("b0", "bandwidth"))))
    assert "class_priority = {2,1};" in prepared.config_text
    trace = "\n".join(
        [f"{6 * i} 0 0 2 1" for i in range(40)]
        + [f"{6 * i + 5} 1 1 2 1" for i in range(40)]) + "\n"

    high_a0 = _run_fork(
        BINARY, tmp_path / "a0_high", prepared.config_text, trace)
    high_a1 = _run_fork(
        BINARY, tmp_path / "a1_high",
        prepared.config_text.replace("class_priority = {2,1};",
                                     "class_priority = {1,2};"), trace)
    avg_a0 = _class_packet_average(high_a0)
    avg_a1 = _class_packet_average(high_a1)
    assert set(avg_a0) == {0, 1}
    assert set(avg_a1) == {0, 1}
    # Class 0 owns the longer path; class 1 owns the shorter one. Raising
    # class 0's rank must lower its latency and raise class 1's.
    assert avg_a0[0] < avg_a1[0]
    assert avg_a0[1] > avg_a1[1]
