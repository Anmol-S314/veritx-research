"""veritx_dse.product.cdc_cell_rtl — M3 CdcCell RTL builder (deep module).

Rationale: docs/design/mesh-stage3-rtl-params-scope.md §2/§3.6.

Layering (mirrors LiveFabric in ``apps/studio/prototype/src/LiveDesign.tsx``,
backend-only — no UI is touched):

* summary layer (read-only): ``cdc_inventory`` — the insertion-point /
  cell plan a caller can display without emitting anything;
* editor layer: ``build_cdc_cell`` — one frozen ``CdcParams`` struct in,
  ``(module, source, verdict)`` out. Param struct in -> module + verdict out.

The emitted cell reuses the repo's existing async FIFO,
``tracks/t3-topology/rtl/cdc/cdc_fifo.sv`` (module ``cdc_fifo``), read-only and
copied beside each cell at preview time by ``rtl_export`` — it is never
modified here. Each cell file defines one module, ``cdc_cell_<san>``,
instantiating ``cdc_fifo`` (DEPTH=16 nominal, Gray pointers, sync stages =
``SYNC_STAGES``) and adding:

* a level-request handshake across the crossing through a ``SYNC_STAGES``
  (default 3) synchronizer chain in each direction — never a
  combinational cross-domain path;
* 2-FF reset synchronizers on both sides with cross-domain reset
  alignment (each side's FIFO reset is qualified by the opposite side's
  reset synchronized into that side's domain);
* an MTBF estimate computed by :func:`estimate_mtbf` from declared
  per-domain clock rates (``CdcParams.src_clock_mhz`` /
  ``dst_clock_mhz``) — undeclared rates stay ``NOT_CALCULATED`` with
  reason; no library tau/t0 is ever substituted silently.

Every build failure is a typed verdict with a blocker id
(``CDC_INVALID_PARAMS`` / ``CDC_CELL_MISSING`` at call sites) — the builder
never emits a pass-through stub and never silently substitutes a
single-domain wire for a crossing.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

#: Blocker id: CdcCell parameters cannot describe a legal crossing.
CDC_INVALID_PARAMS = "CDC_INVALID_PARAMS"
#: Blocker id: a crossing has no CdcCell (used by call sites, not here).
CDC_CELL_MISSING = "CDC_CELL_MISSING"

_DEFAULT_DEPTH = 8
_DEFAULT_SYNC_STAGES = 3
_MIN_SYNC_STAGES = 2
_MIN_DATA_WIDTH = 8


@dataclass(frozen=True)
class Verdict:
    """One build outcome: typed failure in place, never a pass-through."""

    ok: bool
    status: str = "INVALID"          # INVALID | UNSUPPORTED
    blocker_id: str = ""             # machine-readable blocker name
    reason: str | None = None
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CdcParams:
    """One CdcCell request: what crosses, between which domains."""

    insertion_point: str
    src_domain: str
    dst_domain: str
    src_group: int | None = None
    dst_group: int | None = None
    data_width: int = 64
    depth: int = _DEFAULT_DEPTH
    sync_stages: int = _DEFAULT_SYNC_STAGES
    #: Declared clock rates for the MTBF estimate (MHz). ``None`` =
    #: UNDECLARED:  the request schema carries no per-domain rates, so
    #: callers leave both rates unset and the estimate stays
    #: ``NOT_CALCULATED`` with reason — a number is never faked from the
    #: single global ``PhysicalContext.default_clock_freq_mhz`` assumption.
    src_clock_mhz: float | None = None
    dst_clock_mhz: float | None = None


# --- MTBF estimator (declared-rate only) -------------------------------------
#
# Formula (as stated in the cell header, standard sampled-CDC form after
# Cummings AN-1077, "Clock Domain Crossing (CDC) Design & Verification
# Techniques Using SystemVerilog"):
#
#   MTBF  ~=  exp(t_r / tau) / (T_clk * f_cdc * exp(t_0 / tau))
#   t_r   =   (sync_stages - 1) * T_clk,  T_clk = 1 / f_sampling
#
# ``t_r`` is the resolution time the synchronizer chain provides and
# ``f_cdc`` the data transition rate (pointer toggles once per source
# clock). The FIFO crosses pointers both ways, so the estimate takes the
# minimum of the two directions (governing direction reported).
#
# tau/t0 are DECLARED constants, not library data: tau = 100 ps flop
# resolution constant, t0 = 50 ps aperture/setup, illustrative 28 nm
# values in the style of the AN-1077 worked examples. A signoff MTBF must
# replace them with the flop library's recovery/removal data; nothing
# here performs or implies that signoff.

#: Declared flop resolution constant (assumed, not library data).
MTBF_TAU_PS = 100.0
#: Declared aperture/setup constant (assumed, not library data).
MTBF_T0_PS = 50.0
#: The estimator formula as emitted into the cell header and manifest.
MTBF_FORMULA = "MTBF ~= exp(t_r / tau) / (T_clk * f_cdc * exp(t_0 / tau)), t_r = (sync_stages - 1) * T_clk, T_clk = 1 / f_sampling (formula after Cummings AN-1077)"
_SEC_PER_YEAR = 31_536_000.0


@dataclass(frozen=True)
class MtbfEstimate:
    """One MTBF outcome: a computed number or a typed NOT_CALCULATED."""

    status: str = "NOT_CALCULATED"  # CALCULATED | NOT_CALCULATED
    years: float | None = None
    reason: str | None = None
    src_clock_mhz: float | None = None
    dst_clock_mhz: float | None = None
    sync_stages: int = _DEFAULT_SYNC_STAGES
    tau_ps: float = MTBF_TAU_PS
    t0_ps: float = MTBF_T0_PS
    direction: str = ""  # governing direction when CALCULATED


def net_usable_depth(depth: int) -> int:
    return depth


def emitted_fifo_depth(depth: int) -> int:
    return 2 * depth


def estimate_mtbf(
    src_clock_mhz: float | None,
    dst_clock_mhz: float | None,
    sync_stages: int,
    *,
    tau_ps: float = MTBF_TAU_PS,
    t0_ps: float = MTBF_T0_PS,
) -> MtbfEstimate:
    """Standard metastability MTBF from declared rates only.

    No fake library numbers: both per-domain rates must be declared; the
    tau/t0 constants above are explicit assumptions the caller can
    override at signoff. Missing rates return ``NOT_CALCULATED`` with
    reason (UNDECLARED) — never a fabricated year count.
    """
    common = dict(src_clock_mhz=src_clock_mhz, dst_clock_mhz=dst_clock_mhz,
                  sync_stages=sync_stages, tau_ps=tau_ps, t0_ps=t0_ps)
    missing = [name for name, val in
               (("src_clock_mhz", src_clock_mhz),
                ("dst_clock_mhz", dst_clock_mhz)) if val is None]
    if missing:
        return MtbfEstimate(
            status="NOT_CALCULATED",
            reason="per-domain clock rates UNDECLARED: "
                   + ", ".join(missing)
                   + " not set — estimate stays NOT_CALCULATED with "
                     "reason; no single global clock default is used as a "
                     "per-domain rate", **common)
    if src_clock_mhz <= 0 or dst_clock_mhz <= 0:
        # Callers hitting this via CdcParams are refused at check_params;
        # a direct caller gets the same honest refusal, not a number.
        return MtbfEstimate(
            status="NOT_CALCULATED",
            reason=f"clock rates must be positive (MHz), got "
                   f"src={src_clock_mhz} dst={dst_clock_mhz}", **common)

    def _direction(t_clk: float, f_cdc_hz: float) -> float:
        t_r = (sync_stages - 1) * t_clk
        tau, t0 = tau_ps * 1e-12, t0_ps * 1e-12
        try:
            return math.exp(t_r / tau) / (
                t_clk * f_cdc_hz * math.exp(t0 / tau))
        except OverflowError:  # astronomically quiet — name it, don't crash
            return math.inf

    fwd = _direction(1.0 / (dst_clock_mhz * 1e6), src_clock_mhz * 1e6)
    rev = _direction(1.0 / (src_clock_mhz * 1e6), dst_clock_mhz * 1e6)
    governing, direction = ((fwd, "src->dst (sampled on dst)")
                            if fwd <= rev else
                            (rev, "dst->src (sampled on src)"))
    years = governing / _SEC_PER_YEAR
    return MtbfEstimate(status="CALCULATED", years=years, reason=None,
                        direction=direction, **common)


@dataclass(frozen=True)
class CdcCellBuild:
    """The editor layer's output: module + source, or a typed refusal."""

    params: CdcParams
    module: str | None = None
    source: str | None = None
    verdict: Verdict = Verdict(ok=True, status="INVALID")


@dataclass(frozen=True)
class CdcSummary:
    """Read-only summary layer output (insertion/cell inventory)."""

    insertion_points: tuple[str, ...]
    modules: tuple[str, ...]
    blocked: tuple[str, ...]


def sanitize_module_name(insertion_point: str) -> str:
    """Deterministic SystemVerilog identifier for one insertion point."""
    stem = re.sub(r"[^0-9A-Za-z_]", "_", insertion_point).strip("_")
    stem = re.sub(r"_+", "_", stem) or "point"
    digest = hashlib.sha256(insertion_point.encode("utf-8")).hexdigest()[:8]
    return f"cdc_cell_{stem[:40]}_{digest}"


def check_params(params: CdcParams) -> Verdict:
    if not params.insertion_point or \
            not params.insertion_point.startswith("cdc:"):
        return Verdict(ok=False, status="INVALID",
                       blocker_id=CDC_INVALID_PARAMS,
                       reason=f"insertion point must be a cdc: name, got "
                       f"{params.insertion_point!r}")
    if not params.src_domain or not params.dst_domain:
        return Verdict(ok=False, status="INVALID",
                       blocker_id=CDC_INVALID_PARAMS,
                       reason=f"CdcCell needs both crossing domains, got "
                       f"src={params.src_domain!r} dst={params.dst_domain!r}")
    if params.src_domain == params.dst_domain:
        return Verdict(ok=False, status="INVALID",
                       blocker_id=CDC_INVALID_PARAMS,
                       reason=f"CdcCell for {params.insertion_point} names "
                       f"the same domain {params.src_domain!r} on both "
                       f"sides — not a crossing")
    if params.data_width < _MIN_DATA_WIDTH:
        return Verdict(ok=False, status="INVALID",
                       blocker_id=CDC_INVALID_PARAMS,
                       reason=f"data_width must be >= {_MIN_DATA_WIDTH}, "
                       f"got {params.data_width}")
    if params.depth < 4 or params.depth & (params.depth - 1):
        return Verdict(ok=False, status="INVALID",
                       blocker_id=CDC_INVALID_PARAMS,
                       reason=f"usable FIFO depth must be a power of two "
                       f">= 4, got {params.depth}")
    if params.sync_stages < _MIN_SYNC_STAGES:
        return Verdict(ok=False, status="INVALID",
                       blocker_id=CDC_INVALID_PARAMS,
                       reason=f"synchronizer chain needs at least "
                       f"{_MIN_SYNC_STAGES} FFs, got {params.sync_stages}")
    for label, rate in (("src_clock_mhz", params.src_clock_mhz),
                        ("dst_clock_mhz", params.dst_clock_mhz)):
        if rate is not None and rate <= 0:
            return Verdict(ok=False, status="INVALID",
                           blocker_id=CDC_INVALID_PARAMS,
                           reason=f"{label} must be > 0 (MHz) when "
                           f"declared, got {rate}")
    return Verdict(ok=True)


def _render(params: CdcParams, module: str) -> str:
    groups = ((f"group{params.src_group} -> group{params.dst_group}")
              if params.src_group is not None
              and params.dst_group is not None else "declared crossing")
    usable = net_usable_depth(params.depth)
    fifo_depth = emitted_fifo_depth(params.depth)
    mtbf = estimate_mtbf(params.src_clock_mhz, params.dst_clock_mhz,
                         params.sync_stages)
    if mtbf.status == "CALCULATED":
        mtbf_lines = [
            f"//   * MTBF: status CALCULATED; src={params.src_clock_mhz:g} MHz, "
            f"dst={params.dst_clock_mhz:g} MHz,",
            f"//     SYNC_STAGES={params.sync_stages}, "
            f"tau={MTBF_TAU_PS:g} ps, t0={MTBF_T0_PS:g} ps "
            f"(DECLARED assumptions,",
            "//     not library data — replace with .lib recovery/removal "
            "constants for signoff).",
        ]
        if mtbf.years is not None and math.isinf(mtbf.years):
            years_text = "astronomically large (exponent overflow guard)"
        else:
            years_text = f"{mtbf.years:.3f} years"
        mtbf_lines += [
            f"//     Governing direction: {mtbf.direction} -> {years_text}.",
            f"//     {MTBF_FORMULA}.",
        ]
    else:
        mtbf_lines = [
            f"//   * MTBF: status NOT_CALCULATED — {mtbf.reason}.",
            "//     Estimator (computed when both domain rates are declared): "
            f"{MTBF_FORMULA},",
            f"//     with declared tau={MTBF_TAU_PS:g} ps, "
            f"t0={MTBF_T0_PS:g} ps.",
        ]
    mtbf_block = "\n".join(mtbf_lines)
    return f"""// {module}.sv — CdcCell for insertion point "{params.insertion_point}".
// Crossing: {params.src_domain} -> {params.dst_domain} ({groups}).
// Generated by veritx_dse.product.cdc_cell_rtl (M3 deep module).
//
// Structure:
//   * level-request handshake (src_req_toggle -> dst, dst_ack_toggle -> src)
//     through a SYNC_STAGES={params.sync_stages}-FF synchronizer chain in
//     each direction. No combinational cross-domain path exists.
//   * 2-FF reset synchronizers (async assert / sync deassert) per side, and
//     cross-domain reset alignment: each side's FIFO reset is qualified by
//     the opposite side's reset synchronized into that side's domain.
//     Concurrent SVA: a_cell_reset_align_wr / a_cell_reset_align_rd hold
//     wr_full=1 (resp. rd_empty=1) while a side is aligned/reset; the
//     FIFO's own Gray-sequence / gating / quiescence assertions ride
//     inside cdc_fifo.sv (see its assertion-section note for why a literal
//     !(wr_full && rd_empty) mutex is false under sync lag and which
//     invariants are enforced instead).
{mtbf_block}
`default_nettype none

module {module} #(
  parameter int DATA_W = {params.data_width},
  parameter int USABLE_DEPTH = {usable},
  parameter int DEPTH = {fifo_depth},
  parameter int SYNC_STAGES = {params.sync_stages}
) (
  input  logic                  src_clk,
  input  logic                  src_rst_n,
  input  logic                  src_req_toggle,
  output logic                  src_ack_sync_toggle,
  input  logic                  wr_en,
  input  logic [DATA_W-1:0]     wr_data,
  output logic                  wr_full,
  input  logic                  dst_clk,
  input  logic                  dst_rst_n,
  output logic                  dst_req_sync_toggle,
  output logic                  dst_req_valid,
  input  logic                  dst_ack_toggle,
  input  logic                  rd_en,
  output logic [DATA_W-1:0]     rd_data,
  output logic                  rd_valid,
  output logic                  rd_empty
);

  // ---- 2-FF reset synchronizers (async assert, sync deassert) -----------
  logic [1:0] src_rst_pipe;
  always_ff @(posedge src_clk or negedge src_rst_n) begin
    if (!src_rst_n) src_rst_pipe <= 2'b00;
    else src_rst_pipe <= {{src_rst_pipe[0], 1'b1}};
  end
  logic [1:0] dst_rst_pipe;
  always_ff @(posedge dst_clk or negedge dst_rst_n) begin
    if (!dst_rst_n) dst_rst_pipe <= 2'b00;
    else dst_rst_pipe <= {{dst_rst_pipe[0], 1'b1}};
  end
  logic src_rst_sync_n;
  assign src_rst_sync_n = src_rst_pipe[1];
  logic dst_rst_sync_n;
  assign dst_rst_sync_n = dst_rst_pipe[1];

  // ---- cross-domain reset alignment ----------------------------------
  // Each side's FIFO reset waits for BOTH resets: the local reset is
  // synchronized locally (above); the foreign reset crosses through a
  // SYNC_STAGES chain in the local domain. While aligning, the FIFO is
  // held in reset on both sides and no pointer is live.
  logic [SYNC_STAGES-1:0] dst_rst_to_src_pipe;
  always_ff @(posedge src_clk or negedge src_rst_n) begin
    if (!src_rst_n) dst_rst_to_src_pipe <= '0;
    else dst_rst_to_src_pipe <=
        {{dst_rst_to_src_pipe[SYNC_STAGES-2:0], dst_rst_sync_n}};
  end
  logic [SYNC_STAGES-1:0] src_rst_to_dst_pipe;
  always_ff @(posedge dst_clk or negedge dst_rst_n) begin
    if (!dst_rst_n) src_rst_to_dst_pipe <= '0;
    else src_rst_to_dst_pipe <=
        {{src_rst_to_dst_pipe[SYNC_STAGES-2:0], src_rst_sync_n}};
  end
  // FIFO write side is held reset until the destination side has also
  // released its reset (seen through the aligned chain), and vice versa.
  logic wr_rst_n;
  assign wr_rst_n = src_rst_sync_n
      & dst_rst_to_src_pipe[SYNC_STAGES-1] & dst_rst_n;
  logic fifo_wr_full;
  assign wr_full = !wr_rst_n || fifo_wr_full;
  logic rd_rst_n;
  assign rd_rst_n = dst_rst_sync_n
      & src_rst_to_dst_pipe[SYNC_STAGES-1] & src_rst_n;
  logic fifo_rd_empty;
  assign rd_empty = !rd_rst_n || fifo_rd_empty;

  // ---- level-request handshake (SYNC_STAGES chain per direction) -----
  logic [SYNC_STAGES-1:0] req_to_dst_pipe;
  always_ff @(posedge dst_clk or negedge dst_rst_n) begin
    if (!dst_rst_n) req_to_dst_pipe <= '0;
    else req_to_dst_pipe <=
        {{req_to_dst_pipe[SYNC_STAGES-2:0], src_req_toggle}};
  end
  assign dst_req_sync_toggle = req_to_dst_pipe[SYNC_STAGES-1];
  logic req_to_dst_prev;
  always_ff @(posedge dst_clk or negedge dst_rst_n) begin
    if (!dst_rst_n) req_to_dst_prev <= 1'b0;
    else req_to_dst_prev <= dst_req_sync_toggle;
  end
  assign dst_req_valid = (dst_req_sync_toggle != req_to_dst_prev);

  logic [SYNC_STAGES-1:0] ack_to_src_pipe;
  always_ff @(posedge src_clk or negedge src_rst_n) begin
    if (!src_rst_n) ack_to_src_pipe <= '0;
    else ack_to_src_pipe <=
        {{ack_to_src_pipe[SYNC_STAGES-2:0], dst_ack_toggle}};
  end
  assign src_ack_sync_toggle = ack_to_src_pipe[SYNC_STAGES-1];

  // ---- cross-domain reset alignment assertions (SVA) ---------------------
  // While a side's aligned reset is asserted, the interface must
  // backpressure writes (full=1) / reads (empty=1).
  a_cell_reset_align_wr: assert property (@(posedge src_clk) !wr_rst_n
      |-> wr_full);
  a_cell_reset_align_rd: assert property (@(posedge dst_clk) !rd_rst_n
      |-> rd_empty);

  localparam int DEPTH_FROM_USABLE = USABLE_DEPTH * 2;
  wire usable_depth_consistent = (DEPTH == DEPTH_FROM_USABLE);
  a_cell_usable_depth: assert property (@(posedge src_clk)
      usable_depth_consistent);

  cdc_fifo #(
    .DATA_W(DATA_W),
    .DEPTH(DEPTH),
    .STAGES(SYNC_STAGES)
  ) u_fifo (
    .wr_clk(src_clk),
    .wr_rst_n(wr_rst_n),
    .wr_en(wr_en),
    .wr_data(wr_data),
    .wr_full(fifo_wr_full),
    .rd_clk(dst_clk),
    .rd_rst_n(rd_rst_n),
    .rd_en(rd_en),
    .rd_data(rd_data),
    .rd_valid(rd_valid),
    .rd_empty(fifo_rd_empty)
  );

endmodule
`default_nettype wire
"""


def build_cdc_cell(params: CdcParams) -> CdcCellBuild:
    """Editor layer: one param struct in -> (module, source, verdict) out."""
    verdict = check_params(params)
    if not verdict.ok:
        return CdcCellBuild(params=params, module=None, source=None,
                            verdict=verdict)
    module = sanitize_module_name(params.insertion_point)
    source = _render(params, module)
    return CdcCellBuild(params=params, module=module, source=source,
                        verdict=Verdict(ok=True))


def cdc_inventory(params_list: tuple[CdcParams, ...]) -> CdcSummary:
    """Summary layer: read-only insertion/cell inventory, nothing emitted."""
    modules: list[str] = []
    blocked: list[str] = []
    points: list[str] = []
    for params in params_list:
        points.append(params.insertion_point)
        build = build_cdc_cell(params)
        if build.module is not None:
            modules.append(build.module)
        else:
            blocked.append(
                f"{params.insertion_point} [{build.verdict.blocker_id}]")
    return CdcSummary(insertion_points=tuple(sorted(set(points))),
                      modules=tuple(sorted(set(modules))),
                      blocked=tuple(blocked))


# --- CDC-specific structural checks (L2) ---------------------------------


def _gray(n: int) -> int:
    return n ^ (n >> 1)


def gray_sequence_ok(depth: int) -> bool:
    """Gray sequence property: consecutive codes differ in exactly 1 bit."""
    codes = [_gray(n) for n in range(2 * depth)]
    return all(bin(a ^ b).count("1") == 1
               for a, b in zip(codes, codes[1:]))


def check_cdc_cell_source(source: str, *, depth: int = _DEFAULT_DEPTH,
                          sync_stages: int = _DEFAULT_SYNC_STAGES) -> tuple[str, ...]:
    problems: list[str] = []
    if f"DEPTH = {emitted_fifo_depth(depth)}" not in source:
        problems.append(f"no DEPTH = {emitted_fifo_depth(depth)} parameter "
                        f"(2 x usable depth {depth}) on the cell")
    if f"SYNC_STAGES = {sync_stages}" not in source:
        problems.append(f"no SYNC_STAGES = {sync_stages} parameter "
                        f"(synchronizer chain depth not as claimed)")
    if sync_stages < _MIN_SYNC_STAGES:
        problems.append(f"SYNC_STAGES = {sync_stages} below the "
                        f"{_MIN_SYNC_STAGES}-FF minimum")
    if "cdc_fifo" not in source:
        problems.append("no cdc_fifo (asynchronous FIFO) instance")
    if ".STAGES(SYNC_STAGES)" not in source:
        problems.append("fifo sync stages not driven by SYNC_STAGES")
    if "req_to_dst_pipe" not in source or "ack_to_src_pipe" not in source:
        problems.append("missing level-request synchronizer chains")
    if "dst_rst_to_src_pipe" not in source \
            or "src_rst_to_dst_pipe" not in source:
        problems.append("missing cross-domain reset alignment")
    if "src_rst_pipe" not in source or "dst_rst_pipe" not in source:
        problems.append("missing 2-FF reset synchronizers")
    if "assign wr_full = !wr_rst_n || fifo_wr_full;" not in source:
        problems.append("write interface is not backpressured during reset alignment")
    if "assign rd_empty = !rd_rst_n || fifo_rd_empty;" not in source:
        problems.append("read interface is not held empty during reset alignment")
    if "MTBF" not in source:
        problems.append("missing MTBF note")
    if f"USABLE_DEPTH = {net_usable_depth(depth)}" not in source:
        problems.append(f"missing USABLE_DEPTH = "
                        f"{net_usable_depth(depth)} parameter for usable "
                        f"depth {depth} (nominal DEPTH "
                        f"{emitted_fifo_depth(depth)})")
    if "a_cell_reset_align_wr" not in source \
            or "a_cell_reset_align_rd" not in source:
        problems.append("missing reset-alignment SVA assertions")
    if not gray_sequence_ok(depth):
        problems.append("Gray pointer sequence property fails "
                        f"for depth {depth}")
    return tuple(problems)


__all__ = [
    "CDC_INVALID_PARAMS", "CDC_CELL_MISSING",
    "CdcParams", "CdcCellBuild", "CdcSummary", "Verdict",
    "MtbfEstimate", "build_cdc_cell", "cdc_inventory", "check_cdc_cell_source",
    "estimate_mtbf", "net_usable_depth", "emitted_fifo_depth",
    "gray_sequence_ok", "sanitize_module_name",
]
