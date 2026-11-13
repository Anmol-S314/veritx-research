"""The emitter, not a hand edit, produces tool-portable RTL.

The emitted GEC fabric/router is written in readable SystemVerilog: functions
with early ``return``s and ``automatic`` function-local declarations. Verilator
accepts both; Yosys does not, so before this module existed a hand-run script
rewrote the emitted copy and the portable file was an artifact nobody could
regenerate.

These tests pin the fix in the emitter:

* ``portable_sv`` rewrites exactly the three constructs Yosys cannot parse and
  refuses a rewrite it cannot prove safe;
* the emitter's write path (``_write_rtl``) applies it, so a file the product
  writes is already portable and a second pass changes nothing;
* the raw emitter output still carries those constructs, which is what makes
  the rewrite load-bearing rather than decorative;
* when Yosys is installed, it elaborates the portable fabric. That is the
  property C6 needs: a physical flow cannot start on RTL the synthesis tool
  refuses to read.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.product.sv_portable import portable_sv


def _code_only(text: str) -> str:
    """The source without comments, so keyword checks see code and not prose."""
    from veritx_dse.product.sv_portable import strip_comments
    return strip_comments(text)


def test_portable_sv_rewrites_early_and_tail_returns():
    source = """module m #(parameter int K = 4);
  function automatic int pick(input int sel);
    automatic logic unused;
    unused = 1'b0;
    case (sel)
      1: return 10;
      default: return K*K;
    endcase
    return 0;
  endfunction
endmodule
"""
    ported = portable_sv(source)
    assert "return" not in _code_only(ported)
    # The case items assign the function name, and the tail return does too.
    assert "1: pick =  10;" in ported
    assert "default: pick =  K*K;" in ported
    assert "pick =  0;" in ported
    # The enclosing function is already automatic, so the keyword is redundant.
    assert "logic unused;" in ported
    assert "automatic logic unused;" not in ported


def test_portable_sv_keeps_a_block_local_automatic():
    """Block-scope is not function scope: there the keyword carries meaning.

    A variable declared in a procedural block is static, so ``automatic`` is
    what stops a synthesis tool from storing an undefined initial value for
    it. Dropping it inside a function is safe (the function is already
    automatic); dropping it in a block is not.
    """
    source = """module m;
  always_comb begin
    automatic logic y;
    y = 1'b1;
    out = y;
  end
endmodule
"""
    assert portable_sv(source) == source


def test_portable_sv_guards_elaboration_fatal_checks():
    source = """module m;
`ifndef SYNTHESIS
`endif
  initial begin
    if (1 != 1) $fatal(1, "shape");
  end
endmodule
"""
    ported = portable_sv(source)
    assert "`ifndef SYNTHESIS\n  initial begin" in ported
    assert ported.count("`endif") == ported.count("`ifndef SYNTHESIS")


def test_portable_sv_refuses_a_return_it_cannot_prove_is_tail():
    """A mid-body return would change behaviour if rewritten, so it raises."""
    source = """module m;
  function automatic int f(input int a);
    if (a == 0) return 1;
    f = 2;
  endfunction
endmodule
"""
    with pytest.raises(SystemExit):
        portable_sv(source)


def test_portable_sv_is_idempotent():
    source = """module m;
  function automatic logic h(input logic [3:0] f);
    automatic logic unused;
    unused = &{1'b0, f};
    return f[0] == 1'b1;
  endfunction
endmodule
"""
    once = portable_sv(source)
    assert portable_sv(once) == once


def test_emitter_write_path_ports_what_it_writes(tmp_path: Path):
    """``_write_rtl`` is the choke point: testbenches keep their source."""
    from veritx_dse.product.project_top_rtl import _write_rtl

    module = """module m;
  function automatic int f(input int a);
    return a + 1;
  endfunction
endmodule
"""
    rtl = tmp_path / "m.sv"
    _write_rtl(rtl, module)
    assert "return" not in _code_only(rtl.read_text())
    assert "f =  a + 1;" in rtl.read_text()

    tb = tmp_path / "tb_m.sv"
    _write_rtl(tb, "module tb_m;\n  initial begin\n    $display(\"hi\");\n  end\nendmodule\n")
    assert tb.read_text().startswith("module tb_m;")
    assert "$display" in tb.read_text()


def _gec_params():
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.model.topology_intent import GecMode, GecTopologyIntent
    from veritx_dse.product.project_top_rtl import (
        gec_mecs_shared_params_from_request,
    )
    from test_project_top_slice import _family_request

    intent = GecTopologyIntent(GecMode.MULTIDROP, 4, 1, 1, 3)
    request = _family_request(intent)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    return gec_mecs_shared_params_from_request(request, compiled)


def test_emitted_gec_fabric_is_a_rewrite_not_a_coincidence():
    """The raw emitter output needs the rewrite; the emitter applies it."""
    from veritx_dse.product.gec_mecs_credited import render_credited_pool
    from veritx_dse.product.project_top_rtl import render_gec_mecs_shared_fabric

    params = _gec_params()
    raw_fabric = render_gec_mecs_shared_fabric(params)
    raw_pool = render_credited_pool()

    # Readable source: the constructs exist before the rewrite.
    assert re.search(r"^\s*return\b", _code_only(raw_fabric), re.M)
    assert re.search(r"^\s*automatic\s+logic\b", raw_fabric, re.M)

    # After the rewrite, nothing Yosys rejects survives.
    for raw in (raw_fabric, raw_pool):
        ported = portable_sv(raw)
        code = _code_only(ported)
        assert not re.search(r"^\s*return\b", code, re.M), code
        assert not re.search(r"^\s*automatic\s+(logic|int|bit|integer|byte)\b",
                             code, re.M), code
        assert portable_sv(ported) == ported


@pytest.mark.skipif(shutil.which("yosys") is None, reason="yosys not installed")
def test_yosys_elaborates_the_ported_gec_fabric(tmp_path: Path):
    """The point of the rewrite: a synthesis tool can read the shipped fabric."""
    from veritx_dse.product.gec_mecs_credited import render_credited_pool
    from veritx_dse.product.project_top_rtl import render_gec_mecs_shared_fabric

    params = _gec_params()
    # The fabric and the pool are the two files the shared GEC artifact ships;
    # the router is instantiated inside the fabric file by the credited render.
    (tmp_path / "gec_mecs16_fabric.sv").write_text(
        portable_sv(render_gec_mecs_shared_fabric(params)))
    (tmp_path / "tap_credit_pool.sv").write_text(
        portable_sv(render_credited_pool()))

    script = (
        "read_verilog -sv gec_mecs16_fabric.sv tap_credit_pool.sv; "
        "hierarchy -top gec_mecs16_fabric; proc; opt -fast; stat"
    )
    completed = subprocess.run(
        ["yosys", "-q", "-p", script], cwd=tmp_path,
        capture_output=True, text=True, timeout=600)
    assert completed.returncode == 0, completed.stderr[-4000:]
    assert "Can't resolve task name" not in completed.stderr
    assert "TOK_AUTOMATIC" not in completed.stderr


def test_automatic_declaration_of_a_package_type_is_ported():
    source = """module m;
  function automatic logic [3:0] f(input noc_pkg::flit_raw_t flit);
    automatic noc_pkg::flit_raw_t out_f;
    out_f = flit;
    f = out_f[3:0];
  endfunction
endmodule
"""
    ported = portable_sv(source)
    code = _code_only(ported)
    # the function declaration keeps its `automatic`; the local must not
    assert not re.search(r"^\s*automatic\s+\S", code, re.M)
    assert "noc_pkg::flit_raw_t out_f;" in ported


def test_initialised_local_is_split_where_it_stands():
    source = """module m(input logic [3:0] a, output logic [3:0] y);
  always_comb begin
    y = a;
    if (a[0]) begin
      logic [3:0] p = a + 4'd1;
      int used = p - 4'd1;
      y = used[3:0];
    end
  end
endmodule
"""
    ported = portable_sv(source)
    body = [line.strip() for line in ported.splitlines()]
    assert "logic [3:0] p;" in body
    assert "p = a + 4'd1;" in body
    assert "int used;" in body
    assert "used = p - 4'd1;" in body
    # every declaration in the block precedes every statement
    start = body.index("if (a[0]) begin")
    end = body.index("end", start)
    block = body[start + 1:end]
    first_statement = next(i for i, line in enumerate(block) if line.startswith("y ="))
    declarations = [i for i, line in enumerate(block) if line.endswith(";") and "=" not in line]
    assert all(index < first_statement for index in declarations)


def test_a_late_declaration_is_hoisted_to_its_block_top():
    source = """module m(input logic a, output logic y);
  always_comb begin
    y = a;
    if (a) begin
      y = !a;
      automatic int staged = 1;
      y = staged[0];
    end
  end
endmodule
"""
    ported = portable_sv(source)
    body = [line.strip() for line in ported.splitlines()]
    start = body.index("if (a) begin")
    assert body[start + 1] == "automatic int staged;"
    assert "staged = 1;" in body
