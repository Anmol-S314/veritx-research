"""Adversarial mutations of the Qwen acceptance workload (§19).

Every semantic mutation must either change the design identity / the
lowered traffic, or fail the appropriate gate. A mutation that changes
nothing is a silent substitution and fails here.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.product.service import parse_request_doc  # noqa: E402
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.workload.intent_lowering import lower_compile_workload  # noqa: E402

DOC = json.loads((REPO / "tracks" / "t3-topology" / "examples"
                  / "qwen3_moe_tp2_ep4_16tiles-v3.json").read_text())


def _hash(doc: dict) -> str:
    return parse_request_doc(doc).design_hash()


def _classes(doc: dict) -> set[str]:
    lowered = lower_compile_workload(parse_request_doc(doc))
    return {cls for _op, cls in lowered.traffic_class_by_operation}


def _mutate(fn):
    doc = copy.deepcopy(DOC)
    fn(doc)
    return doc


def test_baseline_is_deterministic():
    assert _hash(DOC) == _hash(copy.deepcopy(DOC))
    assert _classes(DOC) == {"tp_collective", "ep_dispatch", "ep_combine"}


@pytest.mark.parametrize("name,fn", [
    ("remove_tp_collective",
     lambda d: d["workload"]["collectives"].pop(0)),
    ("remove_ep_combine",
     lambda d: d["workload"]["collectives"].pop(2)),
    ("swap_tp_for_ep_class",
     lambda d: d["workload"]["collectives"][0].update(
         traffic_class="ep_dispatch")),
    ("change_tp_payload",
     lambda d: d["workload"]["collectives"][0].update(payload_bytes=8192)),
    ("change_link_width",
     lambda d: d["noc_config"].update(link_width=128)),
    ("change_agent_count",
     lambda d: d["agents"][0].update(count=15)),
    ("change_clock",
     lambda d: d["physical"].update(clock_freq_mhz=2000.0)),
    ("drop_one_rank",
     lambda d: d["workload"].update(ep=3)),
    ("duplicate_rank",
     lambda d: d["workload"].update(tp=2, ep=8)),
    ("unsupported_family",
     lambda d: d["workload"].update(model_family="diffusion")),
    ("missing_collective_class",
     lambda d: d["workload"]["collectives"][1].pop("traffic_class")),
    ("change_model_identity",
     lambda d: d["workload"].update(model_name="other/model")),
])
def test_every_mutation_is_detected(name, fn):
    """A mutation must change the design identity, change the lowered
    traffic, or be refused — never silently accepted unchanged."""
    mutated = _mutate(fn)
    refused = False
    identity_changed = traffic_changed = False
    try:
        identity_changed = _hash(mutated) != _hash(DOC)
        traffic_changed = _classes(mutated) != _classes(DOC)
        request = parse_request_doc(mutated)
        FabricCompiler().compile(request)
    except Exception as exc:  # noqa: BLE001 - a typed refusal IS detection
        refused = True
        assert not isinstance(exc, SystemExit)
    assert refused or identity_changed or traffic_changed, (
        f"mutation {name!r} changed neither identity nor traffic and was "
        "not refused — a silent substitution")
