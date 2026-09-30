"""Lineage reclamation — body-level residual dispositions (PHASE 3.1).

The PHASE-3 audit classified six files as "NO STRONG-ONLY SYMBOL" and
stopped there. That test is too shallow: a weaker ancestor can change a
function BODY without adding a symbol. These tests pin the body-level
dispositions actually reached for those six files.

  reports/reports.py        RECLAIM   — constants centralized to core.constants
  reports/artifact.py       RECLAIM   — fail-closed signing (see test_prd_gaps)
  cli/pipeline.py           RECLAIM   — generic safety (see test_lineage_pipeline)
  backend/contracts.py      CURRENT-STRONGER — centralized content_id
  synthesis/event_objective RECLAIM   — script-mode import fallback
  simulation/trace_to_binary COSMETIC — 12 -> 16 byte record documentation
"""
from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO_DSE = Path(__file__).parent.parent

def test_contracts_centralized_content_id_is_hash_equivalent():
    """The stronger lineage built the backend hashes by hand:
        sha256((tag + "\\0" + canonical_json(payload)).encode())
    The current tree delegates to core.artifact.content_id. That helper
    must produce the SAME digest, or a reclamation would be a silent
    identity change."""
    from veritx_dse.core.artifact import canonical_bytes, content_id
    from veritx_dse.core.spec import canonical_json

    payload = {"b": 2, "a": [1, 2, {"z": 3}], "c": {"n": None}}
    domain = "srota/BackendConfigHash/v1"

    strong = hashlib.sha256(
        (f"{domain}\0" + canonical_json(payload)).encode()).hexdigest()
    current = content_id(domain, payload)
    assert current == strong
    assert canonical_bytes(payload) == canonical_json(payload).encode()

def test_contracts_hash_is_domain_separated_and_tamper_sensitive():
    from veritx_dse.core.artifact import content_id
    payload = {"a": 1}
    assert content_id("tag/v1", payload) != content_id("tag/v2", payload)
    assert content_id("tag/v1", payload) != content_id("tag/v1", {"a": 2})

def test_reports_constants_come_from_core_constants():
    """The report module must not carry a SECOND copy of the magic numbers."""
    from veritx_dse.reports import reports as R
    from veritx_dse.core import constants as C

    assert R._ROUTER_AREA_7NM == C.ROUTER_AREA_MM2_7NM
    assert R._LINK_AREA_REF == C.LINK_AREA_MM2_256B_7NM
    assert R._NIC_AREA_7NM == C.NIC_AREA_MM2_7NM
    assert R._RCU_AREA_7NM == C.RCU_AREA_MM2_7NM
    assert R._MECS_AREA_7NM == C.MECS_AREA_MM2_7NM
    assert R._CAPACITANCE_PER_BIT_FF == C.CAPACITANCE_PER_BIT_FF
    assert R._ROUTER_DYNAMIC_MW_PER_MHZ == C.ROUTER_DYNAMIC_MW_PER_MHZ
    assert R._DEFAULT_LEAKAGE_PER_ROUTER_MW == C.LEAKAGE_PER_ROUTER_MW
    assert R._ROUTER_STAGE_DELAY_PS is C.ROUTER_STAGE_DELAY_PS
    assert R._WIRE_DELAY_PS_PER_MM == C.WIRE_DELAY_PS_PER_MM
    assert R._TOPO_WIRE_MM is C.TOPO_WIRE_MM
    assert R._FMAX_DERATING == C.FMAX_DERATING
    src = inspect.getsource(R)
    assert "= 0.010  # mW per MHz" not in src
    assert "_FMAX_DERATING = 0.75" not in src

def test_plane_c_max_vc_has_one_home():
    """compile_model must IMPORT the bound, not re-declare a literal."""
    from veritx_dse.core import constants as C
    from veritx_dse.model import compile_model as M
    assert M.PLANE_C_MAX_VC is C.PLANE_C_MAX_VC
    assert "PLANE_C_MAX_VC: int = 8" not in inspect.getsource(M)

def test_booksim_seed_is_reclaimed_into_core_constants():
    """tools/multi_workload_pareto.py imported BOOKSIM_SEED with a fallback
    shim; the canonical home had lost it."""
    from veritx_dse.core.constants import BOOKSIM_SEED
    assert BOOKSIM_SEED == 42

def _cr_with_collectives(kinds):
    from veritx_dse.model.compile_model import (
        Agent, AgentKind, CollectiveOp, CompileRequest, DependencyGraph,
        ModelFamily, NocConfig, Workload,
    )
    return CompileRequest(
        workload=Workload(
            model_family=ModelFamily.MOE,
            collectives=tuple(CollectiveOp.from_dict(k) for k in kinds),
        ),
        requirements=(),
        agents=(Agent(AgentKind.COMPUTE_TILE, 64),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(),
    )

def test_report_collective_block_is_an_explicit_estimate():
    from veritx_dse.reports.reports import generate_report
    cr = _cr_with_collectives([
        {"kind": "alltoall", "group_size": 8},
        {"kind": "allreduce", "group_size": 8},
    ])
    rep = generate_report(cr, {})
    coll = rep["collectives"]
    assert coll["max_incast_degree"] == 8
    assert "Estimate only" in coll["recommended_vc_buf_note"]
    assert coll["hypercast_messages_saved_estimate"] == {"alltoall/8": 48}
    assert coll["ring_phases_estimate"] == {"allreduce/8": 14}
    assert "not quote as speedup" in coll["hypercast_note"].lower()
    assert "not time" in coll["ring_note"].lower()
    assert coll["vc_floor"] == 2

def test_report_collective_block_handles_no_collectives():
    from veritx_dse.reports.reports import generate_report
    rep = generate_report(_cr_with_collectives([]), {})
    coll = rep["collectives"]
    assert coll["max_incast_degree"] == 0
    assert "no incast sizing" in coll["recommended_vc_buf_note"]
    assert coll["vc_floor"] == 0
    assert coll["hypercast_messages_saved_estimate"] == {}

def test_event_objective_runs_as_a_direct_script():
    """The module advertises `python event_objective.py ...` and has a
    __main__ entry point; it must reach argparse, not die on import."""
    script = REPO_DSE / "veritx_dse/synthesis/event_objective.py"
    r = subprocess.run([sys.executable, str(script), "--help"],
                       capture_output=True, text=True, timeout=60,
                       cwd=str(REPO_DSE))
    assert r.returncode == 0, r.stderr
    assert "Score topology from event stream" in r.stdout

def test_event_objective_still_imports_as_a_package_module():
    from veritx_dse.synthesis import event_objective as eo
    assert callable(eo.ring_schedule)
    assert eo.PIPE_COST is not None and eo.WIRE_COST is not None

def test_trace_to_binary_record_is_16_bytes():
    """'<QHHHH' is 8+2+2+2+2 = 16, not 12. The docstring said 12."""
    from veritx_dse.simulation.trace_to_binary import (
        RECORD_BYTES, RECORD_STRUCT, convert_text_to_binary,
    )
    assert RECORD_BYTES == 16
    assert "12 bytes" not in inspect.getsource(convert_text_to_binary)
    doc = inspect.getdoc(sys.modules[
        "veritx_dse.simulation.trace_to_binary"])
    assert "16 bytes" in doc and "12 bytes" not in doc

def test_trace_to_binary_writes_header_plus_16n(tmp_path):
    from veritx_dse.simulation.trace_to_binary import (
        BINARY_MAGIC, RECORD_BYTES, convert_text_to_binary,
    )
    import struct
    src = tmp_path / "t.trace"
    src.write_text("0 0 0 1 4\n1 1 0 0 4\n")
    out = tmp_path / "t.bin"
    convert_text_to_binary(str(src), str(out))
    blob = out.read_bytes()
    assert len(blob) == 8 + 2 * RECORD_BYTES
    assert struct.unpack("<I", blob[:4])[0] == BINARY_MAGIC
    assert struct.unpack("<I", blob[4:8])[0] == 2
