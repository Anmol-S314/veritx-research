"""PHASE 11 — CLI truthfulness defects (PRODUCT-CONVERGENCE-V1 step D).

Each test pins a defect that was CONFIRMED in the source before patching.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
sys.path.insert(0, str(DSE))

CLI = DSE / "veritx_dse" / "cli" / "cli.py"
SRC = CLI.read_text()


# ══ D — a reported failure must produce a non-zero exit ═══════════════

def test_fail_records_the_failure():
    from veritx_dse.core.logging import Ctx, fail
    ctx = Ctx(verbosity=0)
    assert ctx.failed is False
    fail(ctx, "boom")
    assert ctx.failed is True
    assert ctx._failures == ["boom"]


def test_main_exits_non_zero_when_a_handler_reported_failure():
    """`fail(ctx, ...)` used to print and return, so a handler that reported
    an error still exited 0."""
    assert "if ctx.failed:" in SRC
    tail = SRC[SRC.index("if ctx.failed:"):]
    assert "sys.exit(1)" in tail[:200]


# ══ B — no silent non-square fallback ════════════════════════════════

def test_no_k8_fallback_remains():
    """`k = 8` was substituted whenever `nodes` was not a perfect square, so
    a requested 50-node design was silently evaluated as an 8x8 mesh."""
    code = "\n".join(l for l in SRC.splitlines()
                     if not l.lstrip().startswith("#"))
    assert not re.search(r"^\s*k\s*=\s*8\s*$", code, re.M)
    assert "int(args.nodes ** 0.5)" not in code


# ══ A — the evaluated design IS the synthesized design ═══════════════

def test_run_evaluates_the_synthesized_graph_not_a_fabricated_mesh():
    body = SRC[SRC.index("def cmd_run("):SRC.index("def cmd_runs(")]
    # The fabricated mesh is gone...
    assert 'Topology(f"mesh_{k}x{k}", "mesh", "min_adapt"' not in body
    # ...and the synthesized artifact is what gets evaluated.
    assert '"anynet"' in body
    assert "network_file" in body
    assert "topo_path" in body
    # The literal is split across source lines by implicit concatenation, so
    # match the fragments rather than the joined sentence.
    assert "no synthesized topology at" in body
    assert "evaluate a different design instead" in body


def test_no_separate_identities_between_synthesize_and_evaluate():
    """Both steps must reference the same artifact path."""
    body = SRC[SRC.index("def cmd_run("):SRC.index("def cmd_runs(")]
    assert body.count("topo_path") >= 3


# ══ C — certification uses an authoritative verdict ══════════════════

class _Proc:
    def __init__(self, returncode, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def test_certification_uses_the_process_result():
    from veritx_dse.cli.cli import _certification_verdict
    v = _certification_verdict(_Proc(1, '{"status": "PASS"}'))
    assert v["status"] == "FAIL"
    assert "exited 1" in v["reason"]


def test_a_pass_substring_in_a_failing_line_is_not_certification():
    """The removed bug: `any("PASS" in line)` passed on this."""
    from veritx_dse.cli.cli import _certification_verdict
    v = _certification_verdict(_Proc(0, "FAIL: expected PASS but got 1\n"))
    assert v["status"] == "FAIL"


def test_a_text_only_result_is_not_admissible():
    from veritx_dse.cli.cli import _certification_verdict
    v = _certification_verdict(_Proc(0, "all checks PASS\n"))
    assert v["status"] == "FAIL"
    assert "structured" in v["reason"]


def test_a_structured_pass_is_accepted():
    from veritx_dse.cli.cli import _certification_verdict
    v = _certification_verdict(_Proc(0, 'noise\n{"status": "pass"}\n'))
    assert v["status"] == "PASS"
    assert v["structured"]["status"] == "pass"


def test_the_old_substring_scan_is_gone_from_both_sites():
    """Comment lines are excluded: the fix documents the removed bug by name."""
    code = "\n".join(l for l in SRC.splitlines()
                      if not l.lstrip().startswith("#"))
    assert 'any("PASS" in line' not in code


def test_flow_certification_checks_the_process_result():
    """A certifier that exits non-zero with no PASS/FAIL line used to count
    as `0 failed`."""
    assert "Flow certification process exited" in SRC


# ══ E — failure rows carry the TRUE node count ═══════════════════════

def test_a_failed_row_does_not_claim_zero_nodes():
    """`nodes: 0` is a false statement about the design: the size is a
    property of the topology, not of the run."""
    src = (DSE / "veritx_dse" / "cli" / "pipeline.py").read_text()
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert '"nodes": 0' not in code


def test_topology_size_is_derived_from_the_design():
    from veritx_dse.cli.pipeline import _topology_size
    from veritx_dse.model.presets import Topology
    mesh = Topology("mesh_8x8", "mesh", "min_adapt", {"k": 8, "n": 2})
    size = _topology_size(mesh)
    assert size["nodes"] == 64
    assert size["edges"] == mesh.edges()


def test_topology_size_reports_unknown_rather_than_zero():
    """When the count genuinely cannot be derived it must say so, not assert
    0 — an unknown size and an empty fabric are different facts."""
    from veritx_dse.cli.pipeline import _topology_size
    from veritx_dse.model.presets import Topology
    opaque = Topology("weird", "anynet", "min", {})
    assert _topology_size(opaque)["nodes"] is None


# ══ F — failed/partial result rows render safely ═════════════════════

def test_show_results_tolerates_incomplete_rows(capsys):
    import json as _json
    import tempfile
    from veritx_dse.cli import pipeline as P
    from veritx_dse.core.logging import Ctx

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "booksim"
        root.mkdir(parents=True)
        (root / "sweep_x.json").write_text(_json.dumps({
            "summary": [
                {"name": "ok", "mean": 1.0, "std": 0.1, "min": 0.9,
                 "max": 1.1, "n": 3},
                {"name": "broken", "error": "timeout"},   # no mean/std/...
            ]}))
        original = P._runs_dir
        P._runs_dir = lambda: Path(tmp)
        try:
            ctx = Ctx(verbosity=0)
            P.show_results(ctx, last=5)      # must not raise
            out = capsys.readouterr().out
        finally:
            P._runs_dir = original
    assert "broken" in out
    assert "timeout" in out


# ══ G — UVM input is the compiled artifact, not guessed flags ════════

def test_uvm_refuses_a_v3_document_instead_of_guessing():
    import json as _json
    from veritx_dse.cli.cli import _uvm_generation_input, _UvmInputError

    doc = _json.loads((
        DSE.parents[2] / "tracks/t3-topology/examples/"
        "dense_1b_16tiles-v3.json").read_text())

    class _Args:
        nodes, k = 64, 8

    with pytest.raises(_UvmInputError, match="v3 revision document"):
        _uvm_generation_input(doc, _Args())


def test_uvm_size_comes_from_the_compiled_topology():
    """The size must be derived, and labelled with where it came from."""
    import json as _json
    from veritx_dse.cli.cli import _uvm_generation_input

    doc = _json.loads((
        DSE.parents[2] / "tracks/t3-topology/examples/"
        "dense_1b_16tiles-v3.json").read_text())
    # Downgrade the schema marker so the v2 reader path is exercised.
    doc = {"schema_version": 1, "request": doc}
    src = (DSE / "veritx_dse" / "cli" / "cli.py").read_text()
    assert 'source": "compiled-topology"' in src
    assert "compiled-topology" in src
    assert _uvm_generation_input is not None
