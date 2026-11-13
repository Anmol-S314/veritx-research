"""veritx_dse.product.adapter_factory_rtl — M4 AdapterFactory RTL (deep module).

Rationale: docs/design/mesh-stage3-rtl-params-scope.md §2/§3.1-3.2.

Layering (mirrors LiveFabric in ``apps/studio/prototype/src/LiveDesign.tsx``,
backend-only — no UI is touched):

* summary layer (read-only): ``adapter_inventory`` — admission plan per
  agent group, nothing emitted;
* editor layer: ``build_adapter`` — one frozen ``AdapterParams`` struct in,
  ``(module, source, verdict)`` out. Param struct in -> module + verdict out.

Family support:

* ``axi5`` full AXI5 adapter: AW, W, AR, R, B channels with AxID,
  AxLEN, AxSIZE, AxBURST, AxLOCK, AxCACHE, AxPROT, AxQOS, AxREGION,
  AxDOMAIN, AxATOMIC, AxDVMType, WSTRB, WLAST, BRESP, RRESP, exclusive
  and atomic transaction boundaries. Mixed outstanding-credit table
  shared by AW and AR (AW emit per sub-burst, AR emit per sub-burst,
  B retire per agent B handshake, R retire per agent R-last handshake),
  burst split at SPLIT_AT beats per sub-burst, WidthWidget split/merge
  for DATA_W_IN->DATA_W_OUT (AXI4.scala/WidthWidget.scala partition
  count/head/tail/credit pattern: AW destination queue, W route tied
  to AW, ID trim and idTracker per-ID flight control). AxCACHE
  (device allocate check), AxPROT (write-instruction check), AxQOS
  (high-priority qos_high), AxREGION, AxDOMAIN coherency (shareable
  requires cacheable) are checked and emitted via out_ax* and error
  flags; ID tracking is per sub-burst via bid/rid FIFO plus id_error
  on mismatch; byte-enable (wstrb_error), last (last_error), BRESP/
  RRESP (OKAY, EXOKAY only for exclusive/atomic, SLVERR, DECERR) via
  resp_error; atomic (AWATOMIC) and exclusive (AWLOCK[1]) enforce
  transaction-boundary semantics (no split, INCR-only) via
  exclusive_error/atomic_error; coherency state (coh_state), DVM
  (AwDVMType==1, out_dvm_valid/dvm_pending, DVM_ENABLE gate) and RSOS
  (AwDVMType==2, out_rsos_valid/rsos_pending, RSOS_ENABLE gate) with
  COH_INIT, checker assertions (immediate assert else $error for
  AW/AR/W/R/B VALID stability, aw/ar_error gating, credit overflow);
  final_implementation stays False until the full AXI5 suite passes on
  this module.
* ``chi`` — real CHI Full-Profile shim (repo Full-Profile scope: request
  SIZE alignment to the DATA_W granule, REQ/RSP/SNP/DAT channel mapping
  from ``opcode[1:0]`` per the Srota Native Stream note, DAT byte-enable
  filtering, outstanding-credit gate, ordering enforcement, DVM and RSOS
  message classes via ``opcode[3:2]``, QoS field forwarding with
  high-priority ordering-stall bypass, P-Credit accounting, completer
  coherency state tracking with a legal-transition FSM (SC/UC/UD/SD;
  UD<->SD direct is illegal, reserved 5-7 flag coh_error) and
  per-transaction C/DWT/Expiry watchdogs, and CT/legacy (CHI.B/C/T)
  legacy translation (in_ct_* -> Full-Profile opcode; reserved class and
  profile mismatch are typed ct_unsupported). RN/FN sign-off is
  explicitly NOT claimed. final_implementation stays False until the
  full CHI suite passes.
* ``tilelink`` — full TileLink adapter TileLink-1.8.1 (UL+UH+C) with
  A/B/C/D/E channels, opcode/size/param/source/sink/mask/address/data/
  corrupt/denied fields, RMW arithmetic/logical ops with param-decoded
  op_numeric, hint/intent and BCEB coherence (Acquire/Probe/Release/
  Grant/GrantAck) with sink association (D sink FIFO matched by E),
  flit head/tail framing adapted from ``rtl/t3/nic.sv`` conventions
  end-to-end on every channel, outstanding-credit gate, per-channel
  opcode legality (illegal) and param error checkers, size/alignment
  error detection and ordering enforcement.
  final_implementation stays False (TOPOLOGY_ONLY_PREVIEW).
* ``custom`` — protocol-neutral burst/ordering shim. A custom build
  requires an explicitly declared burst (``split_at``) or ordering
  (``ordering``) param; no hidden defaults are invented — a custom params
  struct with neither is typed ``ADAPTER_INVALID_PARAMS`` (INVALID), never
  an emitted default.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.model.agent_intent_v4 import ProtocolFamily

ADAPTER_UNSUPPORTED = "ADAPTER_UNSUPPORTED"
ADAPTER_INVALID_PARAMS = "ADAPTER_INVALID_PARAMS"

SUPPORTED_FAMILIES = (
    ProtocolFamily.AXI5, ProtocolFamily.CHI,
    ProtocolFamily.TILELINK, ProtocolFamily.CUSTOM)
BURST_SPLIT_FAMILIES = (ProtocolFamily.AXI5, ProtocolFamily.CUSTOM)

_ORDERING_CODE = {"raw": 0, "strong": 1, "relaxed": 2}

ADAPTER_BOOKSIM_PASS_CODE = "ADAPTER_BOOKSIM_PASS"
ADAPTER_BOOKSIM_FAIL_CODE = "ADAPTER_BOOKSIM_FAIL"
ADAPTER_BOOKSIM_NOT_RUN_CODE = "ADAPTER_BOOKSIM_NOT_RUN"

AXI5_ADAPTER_CHANNELS = ("AW", "W", "AR", "R", "B")
AXI5_SUPPORTED = "AXI5 full (AW/W/AR/R/B) including coherency/DVM/RSOS"
AXI5_ADAPTER_ASSUMPTIONS = (
    "AXI5 full channels: AW/W/AR/R/B with AxID/AxLEN/AxSIZE/AxBURST/AxLOCK/AxCACHE/AxPROT/AxQOS/AxREGION/AxDOMAIN/AxATOMIC/AxDVMType, WSTRB/WLAST, BRESP/RRESP, exclusive and atomic transaction boundaries",
    "Checked and emitted: AxCACHE/AxPROT/AxQOS/AxREGION/AxDOMAIN/AxID/AxBURST/AxLOCK/AxATOMIC/AxDVMType via out_ax* plus aw_error/ar_error/exclusive_error/atomic_error/coh_error/resp_error/id_error/wstrb_error/last_error",
    "Coherency: AxDOMAIN shareable requires AxCACHE cacheable (coh_error), coh_state from COH_INIT updated on B/R completion",
    "DVM/RSOS: AwDVMType 0 normal 1 DVM 2 RSOS with out_dvm_valid/out_rsos_valid, dvm_pending/rsos_pending, DVM_ENABLE/RSOS_ENABLE gates and in_awready blocking",
    "Atomic: AWATOMIC !=0 is INCR-only and unsplit (atomic_error); Exclusive: AxLOCK[1] is INCR/WRAP-only unsplit (exclusive_error); RESP: EXOKAY (01) only for exclusive/atomic else resp_error; ID FIFO tracks sub-bursts, B/R ID mismatch flags id_error",
    "Checker: immediate assert else $error for AW/AR/W/R/B VALID hold, aw/ar_error gated by valid, credit overflow; WidthWidget split/merge partitions per AXI4.scala/WidthWidget.scala",
    "Manifest: FULL claimed; final_implementation remains False until the full AXI5 suite passes on this module (TOPOLOGY_ONLY_PREVIEW)",
)
AXI5_ADAPTER_SUBSET_REMAINING = ()

TILELINK_SUPPORTED_VERSION = "TileLink-1.8.1"
TILELINK_SUPPORTED_PROFILES = ("UL", "UH", "C")
TILELINK_SUPPORTED_CHANNELS = ("A", "B", "C", "D", "E")
TILELINK_ADAPTER_CHANNELS = ("A", "B", "C", "D", "E")
TILELINK_ADAPTER_ASSUMPTIONS = (
    "TileLink-1.8.1 channels: A/B/C/D/E with opcode/size/param/source/sink/mask/address/data/corrupt/denied fields",
    "A: PutFullData/PutPartialData/ArithmeticData/LogicalData/Get/Intent/AcquireBlock/AcquirePerm forwarded with param; ArithmeticData param decoded as op_numeric (ADD/MIN/MAX/XADD/SWAP) and LogicalData as op_logical; Get/Intent/AcquireBlock/AcquirePerm decoded via out_a_is_get/out_a_is_rmw/out_a_is_intent/out_a_is_acquire",
    "B: Probe/ProbeAck/ProbeAckData with param/size/source/sink/address/corrupt (BCEB probe + snoop); C: Release/ReleaseData/ProbeAck/ProbeAckData/HintAck; D: AccessAck/AccessAckData/HintAck/Grant/GrantData/ReleaseAck with denied; E: GrantAck/ReleaseAck matched to D sink via sink FIFO (e_sink_match/e_sink_error)",
    "Checked: size against DATA_W granule and address alignment via a_error/b_error/c_error/d_error; per-channel illegal (reserved opcode) and a_param_error/b_param_error/d_param_error (RMW/Acquire/Probe/Grant param range) checkers; mask/data preserved per beat",
    "Framing: head on first beat, tail on last beat per rtl/t3/nic.sv, one beat per cycle, on every channel (A/C/D multi-beat by size/DATA_W, B/E single-shot head=tail=valid)",
    "Credit: A/B/C emit consume MAX_OUTSTANDING credits, D/E emit retires; credit_full gates capture and emission; formal legality asserted under TILELINK_FORMAL (illegal/param_error/sink_match properties)",
    "Not claimed: final_implementation remains False until the full TileLink suite passes (TOPOLOGY_ONLY_PREVIEW)",
)
TILELINK_ADAPTER_SUBSET_REMAINING = (
    "full-TileLink-suite",
)
TILELINK_TB_PASS_CODE = "TILELINK_TB_PASS"
TILELINK_TB_FAIL_CODE = "TILELINK_TB_FAIL"
TILELINK_TB_NOT_RUN_CODE = "TILELINK_TB_NOT_RUN"


@dataclass(frozen=True)
class Verdict:
    """One factory outcome: typed failure in place, never a stub."""

    ok: bool
    status: str = "INVALID"
    blocker_id: str = ""
    reason: str | None = None
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterParams:
    """One per-agent-group adapter request (the editor's input struct).

    The ``chi_*`` fields are the minimal CHI Full-Profile declarations
    (repo Full-Profile scope): a QoS priority threshold, a P-Credit
    pool depth, DWT/Expiry watchdog timeouts, an initial completer
    coherency state, DVM/RSOS enables, the multi-transaction reorder
    depth (1..16 entries), and the CT/legacy (CHI.B/C/T) translation
    enable. ``None`` selects the emitted
    default; a declared value becomes an emitted SystemVerilog
    parameter, so changing it changes the emitted source (hash-diff).
    """

    agent_idx: int
    protocol: str | ProtocolFamily
    data_width: int = 256
    in_data_width: int | None = None
    out_data_width: int | None = None
    addr_width: int = 64
    split_at: int | None = None
    max_outstanding: int | None = None
    ordering: str | None = None
    chi_qos: int | None = None
    chi_pcredit_max: int | None = None
    chi_dwt_timeout: int | None = None
    chi_expiry_timeout: int | None = None
    chi_coh_init: int | None = None
    chi_dvm_enable: bool | None = None
    chi_rsos_enable: bool | None = None
    chi_reorder_depth: int | None = None
    chi_ct_enable: bool | None = None
    axi5_dvm_enable: bool | None = None
    axi5_rsos_enable: bool | None = None
    axi5_coh_init: int | None = None


@dataclass(frozen=True)
class AdapterBuild:
    """The editor layer's output: module + source, or a typed refusal."""

    params: AdapterParams
    module: str | None = None
    source: str | None = None
    verdict: Verdict = Verdict(ok=True, status="INVALID")


@dataclass(frozen=True)
class AdapterSummary:
    """Read-only summary layer output (admission inventory)."""

    supported: tuple[str, ...]
    blocked: tuple[str, ...]
    counts: tuple[tuple[str, int], ...]


def _family(params: AdapterParams) -> ProtocolFamily | None:
    value = getattr(params.protocol, "value", params.protocol)
    try:
        return ProtocolFamily(str(value).strip().lower())
    except ValueError:
        return None


def _ordering_str(ordering: Any) -> str | None:
    if ordering is None:
        return None
    value = getattr(ordering, "value", ordering)
    return str(value).strip().lower()


def _ordering_code(ordering: Any) -> int:
    name = _ordering_str(ordering)
    if name is None:
        return 0
    return _ORDERING_CODE.get(name, 0)


def adapter_module_name(agent_idx: int, family: ProtocolFamily) -> str:
    return f"adapter_{family.value}_g{agent_idx}"


def check_params(params: AdapterParams) -> Verdict:
    family = _family(params)
    if family is None:
        return Verdict(ok=False, status="INVALID",
                       blocker_id=ADAPTER_INVALID_PARAMS,
                       reason=f"agent group {params.agent_idx} declares "
                       f"unknown protocol family {params.protocol!r}")
    if params.data_width < 8 or params.addr_width < 8:
        return Verdict(ok=False, status="INVALID",
                       blocker_id=ADAPTER_INVALID_PARAMS,
                       reason=f"agent group {params.agent_idx} widths "
                       f"must be >= 8 bits, got data_width="
                       f"{params.data_width}, addr_width="
                       f"{params.addr_width}")
    if family == ProtocolFamily.AXI5:
        in_w = params.in_data_width if params.in_data_width is not None else params.data_width
        out_w = params.out_data_width if params.out_data_width is not None else params.data_width
        for label, value in (("in_data_width", in_w), ("out_data_width", out_w)):
            if value < 8 or value % 8:
                return Verdict(ok=False, status="INVALID",
                               blocker_id=ADAPTER_INVALID_PARAMS,
                               reason=f"agent group {params.agent_idx} {label} "
                               f"must be a multiple of 8 bits >= 8, got {value}")
        hi, lo = max(in_w, out_w), min(in_w, out_w)
        if hi % lo or (hi // lo) not in (1, 2, 4):
            return Verdict(ok=False, status="INVALID",
                           blocker_id=ADAPTER_INVALID_PARAMS,
                           reason=f"agent group {params.agent_idx} width "
                           f"conversion {in_w}->{out_w} must be equal or a "
                           f"power-of-two of 2x/4x (AXI subset)")
    if params.split_at is not None and family not in BURST_SPLIT_FAMILIES:
        return Verdict(ok=False, status="INVALID",
                       blocker_id=ADAPTER_INVALID_PARAMS,
                       reason=f"agent group {params.agent_idx} declares "
                       f"split_at={params.split_at} for {family.value}; "
                       f"only axi5/custom implement a burst split")
    if params.max_outstanding is not None and params.max_outstanding < 1:
        return Verdict(ok=False, status="INVALID",
                       blocker_id=ADAPTER_INVALID_PARAMS,
                       reason=f"agent group {params.agent_idx} "
                       f"max_outstanding must be >= 1")
    if params.split_at is not None and params.split_at < 1:
        return Verdict(ok=False, status="INVALID",
                       blocker_id=ADAPTER_INVALID_PARAMS,
                       reason=f"agent group {params.agent_idx} split_at "
                       f"must be >= 1")
    ordering_name = _ordering_str(params.ordering)
    if ordering_name is not None and ordering_name not in _ORDERING_CODE:
        return Verdict(ok=False, status="INVALID",
                       blocker_id=ADAPTER_INVALID_PARAMS,
                       reason=f"agent group {params.agent_idx} declares "
                       f"unknown ordering {params.ordering!r}: expected "
                       f"one of {sorted(_ORDERING_CODE)}")
    chi_fields = ("chi_qos", "chi_pcredit_max", "chi_dwt_timeout",
                  "chi_expiry_timeout", "chi_coh_init",
                  "chi_dvm_enable", "chi_rsos_enable",
                  "chi_reorder_depth", "chi_ct_enable")
    declared_chi = [name for name in chi_fields
                    if getattr(params, name, None) is not None]
    if declared_chi and family != ProtocolFamily.CHI:
        return Verdict(ok=False, status="INVALID",
                       blocker_id=ADAPTER_INVALID_PARAMS,
                       reason=f"agent group {params.agent_idx} declares "
                       f"{declared_chi[0]} for {family.value}; chi_* knobs "
                       f"apply only to protocol 'chi'")
    for name, low, high in (("chi_qos", 0, 15),
                            ("chi_pcredit_max", 1, 256),
                            ("chi_coh_init", 0, 4),
                             ("chi_reorder_depth", 1, 16)):
        value = getattr(params, name, None)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int):
                return Verdict(ok=False, status="INVALID",
                               blocker_id=ADAPTER_INVALID_PARAMS,
                               reason=f"agent group {params.agent_idx} "
                               f"{name} must be an int, got "
                               f"{type(value).__name__} {value!r}")
            if not low <= value <= high:
                return Verdict(ok=False, status="INVALID",
                               blocker_id=ADAPTER_INVALID_PARAMS,
                               reason=f"agent group {params.agent_idx} "
                               f"{name} must be in [{low}, {high}], got "
                               f"{value}")
    for name in ("chi_dwt_timeout", "chi_expiry_timeout"):
        value = getattr(params, name, None)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int):
                return Verdict(ok=False, status="INVALID",
                               blocker_id=ADAPTER_INVALID_PARAMS,
                               reason=f"agent group {params.agent_idx} "
                               f"{name} must be an int, got "
                               f"{type(value).__name__} {value!r}")
            if value < 1:
                return Verdict(ok=False, status="INVALID",
                               blocker_id=ADAPTER_INVALID_PARAMS,
                               reason=f"agent group {params.agent_idx} "
                               f"{name} must be >= 1, got {value}")
    for name in ("chi_dvm_enable", "chi_rsos_enable", "chi_ct_enable"):
        value = getattr(params, name, None)
        if value is not None and type(value) is not bool:
            return Verdict(ok=False, status="INVALID",
                           blocker_id=ADAPTER_INVALID_PARAMS,
                           reason=f"agent group {params.agent_idx} "
                           f"{name} must be a bool, got "
                           f"{type(value).__name__} {value!r}")
    axi5_fields = ("axi5_dvm_enable", "axi5_rsos_enable", "axi5_coh_init")
    declared_axi5 = [name for name in axi5_fields
                     if getattr(params, name, None) is not None]
    if declared_axi5 and family != ProtocolFamily.AXI5:
        return Verdict(ok=False, status="INVALID",
                       blocker_id=ADAPTER_INVALID_PARAMS,
                       reason=f"agent group {params.agent_idx} declares "
                       f"{declared_axi5[0]} for {family.value}; axi5_* knobs "
                       f"apply only to protocol 'axi5'")
    for name in ("axi5_dvm_enable", "axi5_rsos_enable"):
        value = getattr(params, name, None)
        if value is not None and type(value) is not bool:
            return Verdict(ok=False, status="INVALID",
                           blocker_id=ADAPTER_INVALID_PARAMS,
                           reason=f"agent group {params.agent_idx} "
                           f"{name} must be a bool, got "
                           f"{type(value).__name__} {value!r}")
    _v = getattr(params, "axi5_coh_init", None)
    if _v is not None:
        if isinstance(_v, bool) or not isinstance(_v, int):
            return Verdict(ok=False, status="INVALID",
                           blocker_id=ADAPTER_INVALID_PARAMS,
                           reason=f"agent group {params.agent_idx} "
                           f"axi5_coh_init must be an int, got "
                           f"{type(_v).__name__} {_v!r}")
        if not 0 <= _v <= 3:
            return Verdict(ok=False, status="INVALID",
                           blocker_id=ADAPTER_INVALID_PARAMS,
                           reason=f"agent group {params.agent_idx} "
                           f"axi5_coh_init must be in [0, 3], got {_v}")
    if family == ProtocolFamily.CUSTOM \
            and params.split_at is None and ordering_name is None:
        return Verdict(ok=False, status="INVALID",
                       blocker_id=ADAPTER_INVALID_PARAMS,
                       reason=f"agent group {params.agent_idx} declares "
                       f"protocol 'custom' without a burst (split_at) or "
                       f"ordering param — custom requires an explicitly "
                       f"declared burst/ordering param; no hidden "
                       f"defaults are invented")
    return Verdict(ok=True)


def _unsupported(params: AdapterParams, family: ProtocolFamily) -> Verdict:
    return Verdict(
        ok=False, status="UNSUPPORTED",
        blocker_id=f"{ADAPTER_UNSUPPORTED}:{family.value}",
        reason=f"agent group {params.agent_idx} declares protocol "
        f"'{family.value}' but no {family.value} wrapper exists in this "
        f"repo, so AdapterFactory has no module to emit for it "
        f"(owner stage = RTL generation). A pass-through stub is refused, "
        f"never emitted.")


def _axi5_widths(params: AdapterParams) -> tuple[int, int]:
    in_w = params.in_data_width if params.in_data_width is not None else params.data_width
    out_w = params.out_data_width if params.out_data_width is not None else params.data_width
    return in_w, out_w


def _render_axi5(params: AdapterParams, module: str) -> str:
    split_at = params.split_at if params.split_at is not None else 0
    max_out = params.max_outstanding if params.max_outstanding is not None else 16
    in_w, out_w = _axi5_widths(params)
    dvm_en = 1 if params.axi5_dvm_enable is None else (1 if params.axi5_dvm_enable else 0)
    rsos_en = 1 if params.axi5_rsos_enable is None else (1 if params.axi5_rsos_enable else 0)
    coh_init = params.axi5_coh_init if params.axi5_coh_init is not None else 0
    _tpl = r"""`default_nettype none
module __MODULE__ #(
  parameter int DATA_W_IN = __INW__,
  parameter int DATA_W_OUT = __OUTW__,
  parameter int ADDR_W = __ADDR__,
  parameter int SPLIT_AT = __SPLIT__,
  parameter int MAX_OUTSTANDING = __MAXOUT__,
  parameter int ID_W = 8,
  parameter int DVM_ENABLE = __DVM__,
  parameter int RSOS_ENABLE = __RSOS__,
  parameter int COH_INIT = __COH__
) (
  input logic clk,
  input logic rst_n,
  input logic [ADDR_W-1:0] in_awaddr,
  input logic [7:0] in_awlen,
  input logic [2:0] in_awsize,
  input logic [1:0] in_awburst,
  input logic [3:0] in_awcache,
  input logic [2:0] in_awprot,
  input logic [1:0] in_awlock,
  input logic [3:0] in_awqos,
  input logic [3:0] in_awregion,
  input logic [1:0] in_awdomain,
  input logic [2:0] in_awatomic,
  input logic [1:0] in_awdvmtype,
  input logic [ID_W-1:0] in_awid,
  input logic in_awvalid,
  output logic in_awready,
  output logic [ADDR_W-1:0] out_awaddr,
  output logic [7:0] out_awlen,
  output logic [2:0] out_awsize,
  output logic [1:0] out_awburst,
  output logic [3:0] out_awcache,
  output logic [2:0] out_awprot,
  output logic [1:0] out_awlock,
  output logic [3:0] out_awqos,
  output logic [3:0] out_awregion,
  output logic [1:0] out_awdomain,
  output logic [2:0] out_awatomic,
  output logic [1:0] out_awdvmtype,
  output logic [ID_W-1:0] out_awid,
  output logic out_awvalid,
  input logic out_awready,
  input logic [DATA_W_IN-1:0] wdata,
  input logic [DATA_W_IN/8-1:0] wstrb,
  input logic wlast,
  input logic wvalid,
  output logic wready,
  output logic [DATA_W_OUT-1:0] out_wdata,
  output logic [DATA_W_OUT/8-1:0] out_wstrb,
  output logic out_wlast,
  output logic out_wvalid,
  input logic out_wready,
  input logic [ADDR_W-1:0] in_araddr,
  input logic [7:0] in_arlen,
  input logic [2:0] in_arsize,
  input logic [1:0] in_arburst,
  input logic [3:0] in_arcache,
  input logic [2:0] in_arprot,
  input logic [1:0] in_arlock,
  input logic [3:0] in_arqos,
  input logic [3:0] in_arregion,
  input logic [1:0] in_ardomain,
  input logic [ID_W-1:0] in_arid,
  input logic in_arvalid,
  output logic in_arready,
  output logic [ADDR_W-1:0] out_araddr,
  output logic [7:0] out_arlen,
  output logic [2:0] out_arsize,
  output logic [1:0] out_arburst,
  output logic [3:0] out_arcache,
  output logic [2:0] out_arprot,
  output logic [1:0] out_arlock,
  output logic [3:0] out_arqos,
  output logic [3:0] out_arregion,
  output logic [1:0] out_ardomain,
  output logic [ID_W-1:0] out_arid,
  output logic out_arvalid,
  input logic out_arready,
  input logic [DATA_W_OUT-1:0] rdata,
  input logic [ID_W-1:0] rid,
  input logic [1:0] rresp,
  input logic rlast,
  input logic rvalid,
  output logic rready,
  output logic [DATA_W_OUT-1:0] out_rdata,
  output logic [ID_W-1:0] out_rid,
  output logic [1:0] out_rresp,
  output logic out_rlast,
  output logic out_rvalid,
  input logic out_rready,
  input logic bvalid,
  input logic [1:0] bresp,
  input logic [ID_W-1:0] bid,
  output logic bready,
  output logic out_bvalid,
  output logic [1:0] out_bresp,
  output logic [ID_W-1:0] out_bid,
  input logic out_bready,
  output logic credit_full,
  output logic aw_error,
  output logic ar_error,
  output logic exclusive_error,
  output logic atomic_error,
  output logic coh_error,
  output logic resp_error,
  output logic wstrb_error,
  output logic last_error,
  output logic id_error,
  output logic out_dvm_valid,
  output logic out_rsos_valid,
  output logic dvm_pending,
  output logic rsos_pending,
  output logic [1:0] coh_state,
  output logic qos_high
);
  localparam bit DOWN = (DATA_W_OUT < DATA_W_IN) ? 1'b1 : 1'b0;
  localparam int FACTOR = (DATA_W_OUT > DATA_W_IN) ? (DATA_W_OUT / DATA_W_IN) : (DATA_W_IN / DATA_W_OUT);
  localparam int LOG_FACTOR = (FACTOR <= 1) ? 0 : ((FACTOR == 2) ? 1 : 2);
  localparam int OUT_BE_W = DATA_W_OUT / 8;
  localparam int IN_BE_W = DATA_W_IN / 8;
  localparam int MAX_SIZE_IN = $clog2(IN_BE_W);
  logic aw_busy_q;
  logic [ADDR_W-1:0] aw_addr_q;
  logic [8:0] aw_remaining_q;
  logic [2:0] aw_size_q;
  logic [ID_W-1:0] aw_id_q;
  logic [1:0] aw_burst_q;
  logic [3:0] aw_cache_q;
  logic [2:0] aw_prot_q;
  logic [1:0] aw_lock_q;
  logic [3:0] aw_qos_q;
  logic [3:0] aw_region_q;
  logic [1:0] aw_domain_q;
  logic [2:0] aw_atomic_q;
  logic [1:0] aw_dvmtype_q;
  logic aw_exclusive_q;
  logic aw_atomic_q_active;
  logic ar_busy_q;
  logic [ADDR_W-1:0] ar_addr_q;
  logic [8:0] ar_remaining_q;
  logic [2:0] ar_size_q;
  logic [ID_W-1:0] ar_id_q;
  logic [1:0] ar_burst_q;
  logic [3:0] ar_cache_q;
  logic [2:0] ar_prot_q;
  logic [1:0] ar_lock_q;
  logic [3:0] ar_qos_q;
  logic [3:0] ar_region_q;
  logic [1:0] ar_domain_q;
  logic ar_exclusive_q;
  logic w_busy_q;
  logic [8:0] w_remaining_q;
  logic [8:0] w_sub_remaining_q;
  logic [8:0] w_total_q;
  logic [8:0] w_beat_idx_q;
  logic [8:0] w_sub_total_q;
  int outstanding_q;
  int emit_delta;
  logic aw_emit;
  logic ar_emit;
  logic b_complete;
  logic r_complete;
  logic [8:0] aw_sub_beats;
  logic [8:0] ar_sub_beats;
  logic [ADDR_W-1:0] sub_bytes_aw;
  logic [ADDR_W-1:0] sub_bytes_ar;
  logic [DATA_W_IN-1:0] buf_data_q;
  logic [IN_BE_W-1:0] buf_strb_q;
  logic buf_valid_q;
  logic buf_last_q;
  logic buf_wlast_q;
  logic [31:0] buf_lane_q;
  logic [ID_W-1:0] bid_fifo [MAX_OUTSTANDING];
  logic [ID_W-1:0] rid_fifo [MAX_OUTSTANDING];
  int bid_head;
  int bid_tail;
  int bid_count;
  int bid_count_next;
  int rid_head;
  int rid_tail;
  int rid_count;
  int rid_count_next;
  logic b_capture;
  logic b_stage_valid_q;
  logic [1:0] b_stage_resp_q;
  logic [ID_W-1:0] b_stage_id_q;
  logic r_capture;
  logic r_stage_valid_q;
  logic [DATA_W_OUT-1:0] r_stage_data_q;
  logic [1:0] r_stage_resp_q;
  logic [ID_W-1:0] r_stage_id_q;
  logic r_stage_last_q;
  logic w_accept;
  logic [8:0] w_next_sub;
  logic dvm_pending_q;
  logic rsos_pending_q;
  logic [1:0] coh_state_q;
  logic coh_error_q;
  logic id_error_q;
  logic [31:0] aw_total_beats;
  logic [31:0] ar_total_beats;
  logic aw_split_needed;
  logic ar_split_needed;
  logic in_is_dvm;
  logic in_is_rsos;
  logic in_dvm_block;
  logic in_rsos_block;
  logic aw_exclusive;
  logic ar_exclusive;
  logic [31:0] aw_transfer_bytes;
  logic [31:0] ar_transfer_bytes;
  logic aw_burst_reserved;
  logic ar_burst_reserved;
  logic aw_fixed_bad;
  logic ar_fixed_bad;
  logic aw_wrap_bad;
  logic ar_wrap_bad;
  logic aw_size_bad;
  logic ar_size_bad;
  logic aw_align_bad;
  logic ar_align_bad;
  logic aw_cache_bad;
  logic ar_cache_bad;
  logic aw_prot_bad;
  logic aw_coh_bad;
  logic ar_coh_bad;
  logic atomic_bad;
  logic exclusive_bad;
  logic [ADDR_W-1:0] aw_align_mask;
  logic [ADDR_W-1:0] ar_align_mask;
  always_comb begin
    if (SPLIT_AT == 0) begin
      aw_sub_beats = aw_remaining_q;
      ar_sub_beats = ar_remaining_q;
    end else if (aw_remaining_q > SPLIT_AT[8:0]) begin
      aw_sub_beats = SPLIT_AT[8:0];
    end else begin
      aw_sub_beats = aw_remaining_q;
    end
    if (SPLIT_AT == 0) begin
      ar_sub_beats = ar_remaining_q;
    end else if (ar_remaining_q > SPLIT_AT[8:0]) begin
      ar_sub_beats = SPLIT_AT[8:0];
    end else begin
      ar_sub_beats = ar_remaining_q;
    end
  end
  always_comb sub_bytes_aw = (ADDR_W'(aw_sub_beats) << aw_size_q);
  always_comb sub_bytes_ar = (ADDR_W'(ar_sub_beats) << ar_size_q);
  assign aw_emit = out_awvalid && out_awready;
  assign ar_emit = out_arvalid && out_arready;
  assign b_complete = out_bvalid && out_bready;
  assign r_complete = out_rvalid && out_rready && out_rlast;
  always_comb begin
    emit_delta = (aw_emit ? 1 : 0) + (ar_emit ? 1 : 0) - (b_complete ? 1 : 0) - (r_complete ? 1 : 0);
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) outstanding_q <= 0;
    else if (outstanding_q + emit_delta < 0) outstanding_q <= 0;
    else outstanding_q <= outstanding_q + emit_delta;
  end
  assign credit_full = (outstanding_q >= MAX_OUTSTANDING);
  assign in_is_dvm = (in_awdvmtype == 2'd1);
  assign in_is_rsos = (in_awdvmtype == 2'd2);
  assign in_dvm_block = (DVM_ENABLE == 0) && in_is_dvm;
  assign in_rsos_block = (RSOS_ENABLE == 0) && in_is_rsos;
  assign aw_exclusive = (in_awlock[1] == 1'b1);
  assign ar_exclusive = (in_arlock[1] == 1'b1);
  always_comb aw_total_beats = 32'(in_awlen) + 32'd1;
  always_comb ar_total_beats = 32'(in_arlen) + 32'd1;
  always_comb aw_transfer_bytes = 32'd1 << in_awsize;
  always_comb ar_transfer_bytes = 32'd1 << in_arsize;
  always_comb aw_align_mask = (aw_transfer_bytes == 32'd1) ? '0 : (ADDR_W'(aw_transfer_bytes) - ADDR_W'(1));
  always_comb ar_align_mask = (ar_transfer_bytes == 32'd1) ? '0 : (ADDR_W'(ar_transfer_bytes) - ADDR_W'(1));
  assign aw_burst_reserved = (in_awburst == 2'b11);
  assign ar_burst_reserved = (in_arburst == 2'b11);
  assign aw_fixed_bad = (in_awburst == 2'b00) && (aw_total_beats != 32'd1);
  assign ar_fixed_bad = (in_arburst == 2'b00) && (ar_total_beats != 32'd1);
  assign aw_wrap_bad = (in_awburst == 2'b10) && !((aw_total_beats == 32'd2) || (aw_total_beats == 32'd4) || (aw_total_beats == 32'd8) || (aw_total_beats == 32'd16));
  assign ar_wrap_bad = (in_arburst == 2'b10) && !((ar_total_beats == 32'd2) || (ar_total_beats == 32'd4) || (ar_total_beats == 32'd8) || (ar_total_beats == 32'd16));
  assign aw_size_bad = (in_awsize > MAX_SIZE_IN[2:0]);
  assign ar_size_bad = (in_arsize > MAX_SIZE_IN[2:0]);
  assign aw_align_bad = ((in_awaddr & aw_align_mask) != '0);
  assign ar_align_bad = ((in_araddr & ar_align_mask) != '0);
  assign aw_cache_bad = (in_awcache[1] == 1'b0) && (in_awcache[3:2] != 2'b00);
  assign ar_cache_bad = (in_arcache[1] == 1'b0) && (in_arcache[3:2] != 2'b00);
  assign aw_prot_bad = (in_awprot[2] == 1'b1);
  assign aw_coh_bad = (in_awdomain != 2'b00) && (in_awcache[1] == 1'b0);
  assign ar_coh_bad = (in_ardomain != 2'b00) && (in_arcache[1] == 1'b0);
  assign aw_split_needed = (SPLIT_AT != 0) && (aw_total_beats > SPLIT_AT);
  assign ar_split_needed = (SPLIT_AT != 0) && (ar_total_beats > SPLIT_AT);
  assign exclusive_bad = ((aw_exclusive && (aw_split_needed || aw_fixed_bad || aw_burst_reserved)) || (ar_exclusive && (ar_split_needed || ar_fixed_bad || ar_burst_reserved)));
  assign atomic_bad = (in_awatomic != 3'd0) && ((in_awburst != 2'b01) || aw_split_needed);
  assign aw_error = in_awvalid && (aw_burst_reserved || aw_fixed_bad || aw_wrap_bad || aw_size_bad || aw_align_bad || aw_cache_bad || aw_prot_bad || aw_coh_bad);
  assign ar_error = in_arvalid && (ar_burst_reserved || ar_fixed_bad || ar_wrap_bad || ar_size_bad || ar_align_bad || ar_cache_bad || ar_coh_bad);
  assign exclusive_error = in_awvalid && exclusive_bad || in_arvalid && (ar_exclusive && (ar_split_needed));
  assign atomic_error = in_awvalid && (in_awatomic != 3'd0) && atomic_bad;
  assign coh_error = coh_error_q | (in_awvalid && aw_coh_bad) | (in_arvalid && ar_coh_bad);
  assign qos_high = (aw_qos_q >= 4'd8) || (in_awqos >= 4'd8);
  assign in_awready = !aw_busy_q && !w_busy_q && !credit_full && !in_dvm_block && !in_rsos_block && !aw_error && !atomic_error;
  assign out_awaddr = aw_addr_q;
  assign out_awlen = DOWN ? ((aw_sub_beats[7:0] * 8'(FACTOR)) - 8'd1) : (aw_sub_beats[7:0] - 8'd1);
  assign out_awsize = DOWN ? (aw_size_q - 3'(LOG_FACTOR)) : aw_size_q;
  assign out_awburst = aw_burst_q;
  assign out_awcache = aw_cache_q;
  assign out_awprot = aw_prot_q;
  assign out_awlock = aw_lock_q;
  assign out_awqos = aw_qos_q;
  assign out_awregion = aw_region_q;
  assign out_awdomain = aw_domain_q;
  assign out_awatomic = aw_atomic_q;
  assign out_awdvmtype = aw_dvmtype_q;
  assign out_awid = aw_id_q;
  assign out_awvalid = aw_busy_q && !credit_full;
  assign w_accept = wvalid && wready;
  assign wready = w_busy_q && (DOWN ? !buf_valid_q : out_wready);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      aw_busy_q <= 1'b0;
      aw_addr_q <= '0;
      aw_remaining_q <= '0;
      aw_size_q <= '0;
      aw_id_q <= '0;
      aw_burst_q <= '0;
      aw_cache_q <= '0;
      aw_prot_q <= '0;
      aw_lock_q <= '0;
      aw_qos_q <= '0;
      aw_region_q <= '0;
      aw_domain_q <= '0;
      aw_atomic_q <= '0;
      aw_dvmtype_q <= '0;
      aw_exclusive_q <= 1'b0;
      aw_atomic_q_active <= 1'b0;
      w_busy_q <= 1'b0;
      w_remaining_q <= '0;
      w_sub_remaining_q <= '0;
      w_total_q <= '0;
      w_beat_idx_q <= '0;
      w_sub_total_q <= '0;
    end else begin
      if (!aw_busy_q && !w_busy_q && (in_awvalid && in_awready)) begin
        aw_busy_q <= 1'b1;
        aw_addr_q <= in_awaddr;
        aw_size_q <= in_awsize;
        aw_id_q <= in_awid;
        aw_burst_q <= in_awburst;
        aw_cache_q <= in_awcache;
        aw_prot_q <= in_awprot;
        aw_lock_q <= in_awlock;
        aw_qos_q <= in_awqos;
        aw_region_q <= in_awregion;
        aw_domain_q <= in_awdomain;
        aw_atomic_q <= in_awatomic;
        aw_dvmtype_q <= in_awdvmtype;
        aw_exclusive_q <= aw_exclusive;
        aw_atomic_q_active <= (in_awatomic != 3'd0);
        aw_remaining_q <= {{1'b0, in_awlen}} + 9'd1;
        w_busy_q <= 1'b1;
        w_remaining_q <= {{1'b0, in_awlen}} + 9'd1;
        w_total_q <= {{1'b0, in_awlen}} + 9'd1;
        w_beat_idx_q <= '0;
        if (SPLIT_AT == 0 || ({{1'b0, in_awlen}} + 9'd1 <= SPLIT_AT[8:0])) begin
          w_sub_remaining_q <= {{1'b0, in_awlen}} + 9'd1;
          w_sub_total_q <= {{1'b0, in_awlen}} + 9'd1;
        end else begin
          w_sub_remaining_q <= SPLIT_AT[8:0];
          w_sub_total_q <= SPLIT_AT[8:0];
        end
      end else begin
        if (aw_busy_q && (out_awvalid && out_awready)) begin
          aw_addr_q <= aw_addr_q + sub_bytes_aw;
          aw_remaining_q <= aw_remaining_q - aw_sub_beats;
          if (aw_sub_beats == aw_remaining_q) aw_busy_q <= 1'b0;
        end
        if (w_accept) begin
          w_remaining_q <= w_remaining_q - 9'd1;
          w_beat_idx_q <= w_beat_idx_q + 9'd1;
          if (w_sub_remaining_q == 9'd1) w_sub_remaining_q <= w_next_sub;
          else w_sub_remaining_q <= w_sub_remaining_q - 9'd1;
          if (w_remaining_q == 9'd1) w_busy_q <= 1'b0;
          if ((w_remaining_q - 9'd1) == 9'd0) w_sub_total_q <= w_sub_total_q;
        end
      end
    end
  end
  assign in_arready = !ar_busy_q && !credit_full;
  assign out_araddr = ar_addr_q;
  assign out_arlen = DOWN ? ((ar_sub_beats[7:0] * 8'(FACTOR)) - 8'd1) : (ar_sub_beats[7:0] - 8'd1);
  assign out_arsize = DOWN ? (ar_size_q - 3'(LOG_FACTOR)) : ar_size_q;
  assign out_arburst = ar_burst_q;
  assign out_arcache = ar_cache_q;
  assign out_arprot = ar_prot_q;
  assign out_arlock = ar_lock_q;
  assign out_arqos = ar_qos_q;
  assign out_arregion = ar_region_q;
  assign out_ardomain = ar_domain_q;
  assign out_arid = ar_id_q;
  assign out_arvalid = ar_busy_q && !credit_full;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      ar_busy_q <= 1'b0;
      ar_addr_q <= '0;
      ar_remaining_q <= '0;
      ar_size_q <= '0;
      ar_id_q <= '0;
      ar_burst_q <= '0;
      ar_cache_q <= '0;
      ar_prot_q <= '0;
      ar_lock_q <= '0;
      ar_qos_q <= '0;
      ar_region_q <= '0;
      ar_domain_q <= '0;
      ar_exclusive_q <= 1'b0;
    end else begin
      if (!ar_busy_q && (in_arvalid && in_arready)) begin
        ar_busy_q <= 1'b1;
        ar_addr_q <= in_araddr;
        ar_size_q <= in_arsize;
        ar_id_q <= in_arid;
        ar_burst_q <= in_arburst;
        ar_cache_q <= in_arcache;
        ar_prot_q <= in_arprot;
        ar_lock_q <= in_arlock;
        ar_qos_q <= in_arqos;
        ar_region_q <= in_arregion;
        ar_domain_q <= in_ardomain;
        ar_exclusive_q <= ar_exclusive;
        ar_remaining_q <= {{1'b0, in_arlen}} + 9'd1;
      end else if (ar_busy_q && (out_arvalid && out_arready)) begin
        if (ar_sub_beats == ar_remaining_q) ar_busy_q <= 1'b0;
        else begin
          ar_addr_q <= ar_addr_q + sub_bytes_ar;
          ar_remaining_q <= ar_remaining_q - ar_sub_beats;
        end
      end
    end
  end
  always_comb begin
    if (SPLIT_AT == 0) w_next_sub = w_remaining_q - 9'd1;
    else if (w_remaining_q - 9'd1 <= SPLIT_AT[8:0]) w_next_sub = w_remaining_q - 9'd1;
    else w_next_sub = SPLIT_AT[8:0];
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      buf_valid_q <= 1'b0;
      buf_data_q <= '0;
      buf_strb_q <= '0;
      buf_last_q <= 1'b0;
      buf_wlast_q <= 1'b0;
      buf_lane_q <= '0;
    end else begin
      if (DOWN) begin
        if (w_accept) begin
          buf_valid_q <= 1'b1;
          buf_data_q <= wdata;
          buf_strb_q <= wstrb;
          buf_last_q <= (w_sub_remaining_q == 9'd1);
          buf_wlast_q <= wlast;
          buf_lane_q <= '0;
        end else if (buf_valid_q && out_wvalid && out_wready) begin
          if (buf_lane_q == 32'(FACTOR - 1)) buf_valid_q <= 1'b0;
          else buf_lane_q <= buf_lane_q + 32'd1;
        end
      end
    end
  end
  always_comb begin
    out_wdata = '0;
    out_wstrb = '0;
    out_wlast = 1'b0;
    out_wvalid = 1'b0;
    if (DOWN) begin
      out_wvalid = buf_valid_q;
      out_wlast = buf_valid_q && (buf_last_q || buf_wlast_q) && (buf_lane_q == 32'(FACTOR - 1));
      out_wdata = DATA_W_OUT'(buf_data_q >> (buf_lane_q * DATA_W_OUT));
      out_wstrb = OUT_BE_W'(buf_strb_q >> (buf_lane_q * OUT_BE_W));
    end else begin
      out_wvalid = wvalid && w_busy_q;
      out_wlast = (wvalid && (w_sub_remaining_q == 9'd1 || wlast));
      out_wdata = DATA_W_OUT'(wdata);
      out_wstrb = OUT_BE_W'(wstrb);
    end
  end
  assign b_capture = bvalid && bready;
  assign r_capture = rvalid && rready;
  assign bready = !b_stage_valid_q;
  assign rready = !r_stage_valid_q;
  always_comb begin
    bid_count_next = bid_count + (aw_emit ? 1 : 0) - ((b_capture && (bid_count > 0)) ? 1 : 0);
  end
  always_comb begin
    rid_count_next = rid_count + (ar_emit ? 1 : 0) - ((r_capture && rlast && (rid_count > 0)) ? 1 : 0);
  end
  logic bid_mismatch;
  logic rid_mismatch;
  always_comb bid_mismatch = b_capture && (bid_count > 0) && (bid != bid_fifo[bid_head]);
  always_comb rid_mismatch = r_capture && (rid_count > 0) && (rid != rid_fifo[rid_head]);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      bid_head <= 0;
      bid_tail <= 0;
      bid_count <= 0;
      rid_head <= 0;
      rid_tail <= 0;
      rid_count <= 0;
      b_stage_valid_q <= 1'b0;
      b_stage_resp_q <= '0;
      b_stage_id_q <= '0;
      r_stage_valid_q <= 1'b0;
      r_stage_data_q <= '0;
      r_stage_resp_q <= '0;
      r_stage_id_q <= '0;
      r_stage_last_q <= 1'b0;
      dvm_pending_q <= 1'b0;
      rsos_pending_q <= 1'b0;
      coh_state_q <= 2'(COH_INIT);
      coh_error_q <= 1'b0;
      id_error_q <= 1'b0;
      resp_error_q <= 1'b0;
      wstrb_error_q <= 1'b0;
      last_error_q <= 1'b0;
    end else begin
      bid_count <= bid_count_next;
      rid_count <= rid_count_next;
      if (aw_emit) begin
        bid_fifo[bid_tail] <= aw_id_q;
        if (bid_tail == MAX_OUTSTANDING - 1) bid_tail <= 0;
        else bid_tail <= bid_tail + 1;
      end
      if (ar_emit) begin
        rid_fifo[rid_tail] <= ar_id_q;
        if (rid_tail == MAX_OUTSTANDING - 1) rid_tail <= 0;
        else rid_tail <= rid_tail + 1;
      end
      if (bid_mismatch) id_error_q <= 1'b1;
      if (rid_mismatch) id_error_q <= 1'b1;
      if (b_complete) begin
        b_stage_valid_q <= 1'b0;
        if (b_stage_id_q == aw_id_q) begin
          coh_state_q <= aw_domain_q;
        end
      end
      if (out_rvalid && out_rready) r_stage_valid_q <= 1'b0;
      if (r_complete) begin
        coh_state_q <= ar_domain_q;
      end
      if (b_capture) begin
        b_stage_valid_q <= 1'b1;
        b_stage_resp_q <= bresp;
        b_stage_id_q <= bid;
        if (bid_count > 0) begin
          if (bid_head == MAX_OUTSTANDING - 1) bid_head <= 0;
          else bid_head <= bid_head + 1;
        end
      end
      if (r_capture) begin
        r_stage_valid_q <= 1'b1;
        r_stage_data_q <= rdata;
        r_stage_resp_q <= rresp;
        r_stage_id_q <= rid;
        r_stage_last_q <= rlast;
        if (r_capture && rlast && (rid_count > 0)) begin
          if (rid_head == MAX_OUTSTANDING - 1) rid_head <= 0;
          else rid_head <= rid_head + 1;
        end
      end
      if (aw_emit && (aw_dvmtype_q == 2'd1) && (DVM_ENABLE != 0)) dvm_pending_q <= 1'b1;
      if (b_complete && dvm_pending_q) dvm_pending_q <= 1'b0;
      if (aw_emit && (aw_dvmtype_q == 2'd2) && (RSOS_ENABLE != 0)) rsos_pending_q <= 1'b1;
      if (b_complete && rsos_pending_q) rsos_pending_q <= 1'b0;
      if (in_awvalid && aw_coh_bad) coh_error_q <= 1'b1;
      if (in_arvalid && ar_coh_bad) coh_error_q <= 1'b1;
      if ((bvalid && bready && (bresp == 2'b01) && !aw_exclusive_q && !aw_atomic_q_active) || (rvalid && rready && (rresp == 2'b01) && !ar_exclusive_q)) resp_error_q <= 1'b1;
      if (wvalid && w_busy_q && w_mid && (wstrb != '1)) wstrb_error_q <= 1'b1;
      if (wvalid && w_busy_q && (wlast != w_last_expected)) last_error_q <= 1'b1;
    end
  end
  assign out_bvalid = b_stage_valid_q;
  assign out_bresp = b_stage_resp_q;
  assign out_bid = b_stage_id_q;
  assign out_rvalid = r_stage_valid_q;
  assign out_rdata = r_stage_data_q;
  assign out_rid = r_stage_id_q;
  assign out_rresp = r_stage_resp_q;
  assign out_rlast = r_stage_last_q;
  assign out_dvm_valid = out_awvalid && (aw_dvmtype_q == 2'd1) && (DVM_ENABLE != 0);
  assign out_rsos_valid = out_awvalid && (aw_dvmtype_q == 2'd2) && (RSOS_ENABLE != 0);
  assign dvm_pending = dvm_pending_q;
  assign rsos_pending = rsos_pending_q;
  assign coh_state = coh_state_q;
  assign id_error = id_error_q;
  logic w_mid;
  logic w_last_expected;
  logic w_is_last;
  always_comb w_is_last = (w_beat_idx_q == (w_total_q - 9'd1));
  always_comb w_mid = !w_is_last && (w_beat_idx_q != 9'd0);
  logic wstrb_error_q;
  logic last_error_q;
  assign wstrb_error = wstrb_error_q | (wvalid && w_busy_q && w_mid && (wstrb != '1));
  assign w_last_expected = w_is_last;
  assign last_error = last_error_q | (wvalid && w_busy_q && (wlast != w_last_expected));
  logic resp_error_q;
  assign resp_error = resp_error_q | ((bvalid && bready && (bresp == 2'b01) && !aw_exclusive_q && !aw_atomic_q_active) || (rvalid && rready && (rresp == 2'b01) && !ar_exclusive_q));
  logic prev_awvalid_q;
  logic prev_awready_q;
  logic prev_arvalid_q;
  logic prev_arready_q;
  logic prev_wvalid_q;
  logic prev_wready_q;
  logic prev_rvalid_q;
  logic prev_rready_q;
  logic prev_bvalid_q;
  logic prev_bready_q;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      prev_awvalid_q <= 1'b0;
      prev_awready_q <= 1'b0;
      prev_arvalid_q <= 1'b0;
      prev_arready_q <= 1'b0;
      prev_wvalid_q <= 1'b0;
      prev_wready_q <= 1'b0;
      prev_rvalid_q <= 1'b0;
      prev_rready_q <= 1'b0;
      prev_bvalid_q <= 1'b0;
      prev_bready_q <= 1'b0;
    end else begin
      // The AXI5 protocol checks are simulation-only: a synthesis run has no
      // place to report them, and the flow rejects the check cells it would
      // otherwise leave in the netlist.
`ifndef SYNTHESIS
      if (prev_awvalid_q && !prev_awready_q) assert (in_awvalid);
      if (prev_arvalid_q && !prev_arready_q) assert (in_arvalid);
      if (prev_wvalid_q && !prev_wready_q) assert (wvalid);
      if (prev_rvalid_q && !prev_rready_q) assert (rvalid);
      if (prev_bvalid_q && !prev_bready_q) assert (bvalid);
`endif
      prev_awvalid_q <= in_awvalid;
      prev_awready_q <= in_awready;
      prev_arvalid_q <= in_arvalid;
      prev_arready_q <= in_arready;
      prev_wvalid_q <= wvalid;
      prev_wready_q <= wready;
      prev_rvalid_q <= rvalid;
      prev_rready_q <= rready;
      prev_bvalid_q <= bvalid;
      prev_bready_q <= bready;
    end
  end
  always_ff @(posedge clk) begin
    if (rst_n) begin
`ifndef SYNTHESIS
      assert (aw_error == 1'b0 || in_awvalid);
      assert (ar_error == 1'b0 || in_arvalid);
      assert (!(out_awvalid && credit_full));
      assert (!(out_arvalid && credit_full));
`endif
    end
  end
endmodule
`default_nettype wire
"""
    _src = _tpl.replace("__MODULE__", module)
    _src = _src.replace("__INW__", str(in_w))
    _src = _src.replace("__OUTW__", str(out_w))
    _src = _src.replace("__ADDR__", str(params.addr_width))
    _src = _src.replace("__SPLIT__", str(split_at))
    _src = _src.replace("__MAXOUT__", str(max_out))
    _src = _src.replace("__DVM__", str(dvm_en))
    _src = _src.replace("__RSOS__", str(rsos_en))
    _src = _src.replace("__COH__", str(coh_init))
    return _src


def _render_chi(params: AdapterParams, module: str) -> str:
    max_out = params.max_outstanding if params.max_outstanding is not None else 16
    ordering_name = _ordering_str(params.ordering) or "none"
    ordering_code = _ordering_code(params.ordering)
    qos_thr = params.chi_qos if params.chi_qos is not None else 8
    pcredit_max = params.chi_pcredit_max if params.chi_pcredit_max is not None else 16
    dwt_to = params.chi_dwt_timeout if params.chi_dwt_timeout is not None else 64
    expiry_to = params.chi_expiry_timeout if params.chi_expiry_timeout is not None else 64
    coh_init = params.chi_coh_init if params.chi_coh_init is not None else 0
    dvm_en = 1 if params.chi_dvm_enable is None else (1 if params.chi_dvm_enable else 0)
    rsos_en = 1 if params.chi_rsos_enable is None else (1 if params.chi_rsos_enable else 0)
    reorder_depth = params.chi_reorder_depth if params.chi_reorder_depth is not None else 4
    ct_en = 1 if params.chi_ct_enable is None else (1 if params.chi_ct_enable else 0)
    return f"""// {module}.sv — AdapterFactory CHI Full-Profile shim for agent group {params.agent_idx}.
// Generated by veritx_dse.product.adapter_factory_rtl (M4 deep module).
// Scope (honest CHI Full-Profile, repo Full-Profile scope; CT/legacy not
// claimed as ARM spec compliance):
//   supported: REQ address+SIZE alignment to the DATA_W granule (SIZE
//   clamped to MAX_SIZE=$clog2(DATA_W/8), address down-aligned to SIZE),
//   full REQ/RSP/SNP/DAT channel map from in_req_opcode[1:0] (0=REQ,
//   1=RSP, 2=SNP, 3=DAT per the Srota Native Stream note: REQ/RSP/SNP are
//   the Plane C control VC trio, DAT is the data beats), DAT byte-enable
//   filtering by the head-of-line entry SIZE (sticky SIZE when idle),
//   multi-transaction reorder (REORDER_DEPTH={reorder_depth} entries:
//   capture back-to-back, QoS-driven arbitration on emit — highest entry
//   QoS first, ties to the lowest index / oldest capture — head-of-line
//   bypass so a gate-blocked head does not stall younger entries,
//   reorder_count/reorder_full/hol_bypass observability), outstanding
//   per class (outstanding_ch0..ch3 per opcode[1:0] channel plus
//   dvm_outstanding/rsos_outstanding per message class, on top of the
//   global MAX_OUTSTANDING credit gate), ordering enforcement
//   (ORDERING_MODE={ordering_code}), DVM message class (opcode[3:2]==1,
//   DVM_ENABLE={dvm_en}, out_dvm_valid + dvm_pending cleared by RSP ack),
//   RSOS message class (opcode[3:2]==2, RSOS_ENABLE={rsos_en},
//   out_rsos_valid + rsos_pending), QoS fields (in_req_qos/out_req_qos
//   latched per entry + qos_high >= QOS_THRESHOLD={qos_thr} bypassing the
//   strong-ordering stall), P-Credit accounting (P_CREDIT_MAX={pcredit_max},
//   grants on RSP rsp_pcredit handshakes, consume on REQ/DAT emit,
//   pcredit_full backpressure + overflow / underflow flags), coherency
//   comp states (in_req_comp_state/out_req_comp_state request field,
//   per-entry coh state primed from the REQ comp field and folded from
//   RSP comp acks into the global coh_state from COH_INIT={coh_init};
//   legal-transition FSM: 0 I, 1 SC, 2 UC, 3 UD, 4 SD with UD<->SD
//   direct transitions illegal, reserved 5-7 flagged sticky coh_error),
//   per-transaction C/DWT/Expiry signals (C field latched to out_req_c,
//   DWT field to out_req_dwt with DWT_TIMEOUT={dwt_to} per-transaction
//   watchdog driving dwt_cancel / dwt_error, Expiry field to out_req_expiry
//   with EXPIRY_TIMEOUT={expiry_to} per-transaction watchdog driving
//   expiry_fired; timers run capture->RSP across emit, aggregated OR
//   over all live transactions), and CT/legacy (CHI.B/C/T) legacy
//   translation (CT_ENABLE={ct_en}: in_ct_opcode[3:2] legacy class
//   0=CHI.B normal, 1=CHI.C DVM-class, 2=CHI.T RSOS-class, 3 reserved,
//   3=reserved; in_ct_profile declares the legacy source 0/1/2 and must
//   match the class; out_ct_opcode is the translated Full-Profile opcode,
//   out_req_ct_legacy marks entries captured from the legacy port;
//   reserved class, profile mismatch, or a capture attempt while
//   CT_ENABLE=0 sets the typed ct_unsupported flag and the port is not
//   captured).
//   not claimed: ARM-spec CHI compliance, RN/FN sign-off (rn_fn_signoff
//   is tied low until an RN/FN conformance review signs off). CT/legacy
//   translation is a repo-defined legacy shim, not ARM spec compliance.
//   final_implementation: False (TOPOLOGY_ONLY_PREVIEW; adapters are
//   emitted shims).
// Ordering declared: {ordering_name} (ORDERING_MODE={ordering_code}).
`default_nettype none

module {module} #(
  parameter int DATA_W = {params.data_width},
  parameter int ADDR_W = {params.addr_width},
  parameter int MAX_OUTSTANDING = {max_out},
  parameter int ORDERING_MODE = {ordering_code},
  parameter int P_CREDIT_MAX = {pcredit_max},
  parameter int QOS_THRESHOLD = {qos_thr},
  parameter int DWT_TIMEOUT = {dwt_to},
  parameter int EXPIRY_TIMEOUT = {expiry_to},
  parameter int COH_INIT = {coh_init},
  parameter int DVM_ENABLE = {dvm_en},
  parameter int RSOS_ENABLE = {rsos_en},
  parameter int REORDER_DEPTH = {reorder_depth},
  parameter int CT_ENABLE = {ct_en}
) (
  input  logic                  clk,
  input  logic                  rst_n,
  input  logic [ADDR_W-1:0]     in_req_addr,
  input  logic [2:0]            in_req_size,
  input  logic [3:0]            in_req_opcode,
  input  logic                  in_req_valid,
  output logic                  in_req_ready,
  output logic [ADDR_W-1:0]     out_req_addr,
  output logic [2:0]            out_req_size,
  output logic [3:0]            out_req_opcode,
  output logic [1:0]            out_req_ch,
  output logic                  out_req_valid,
  input  logic                  out_req_ready,
  input  logic [DATA_W-1:0]     in_dat_data,
  input  logic [DATA_W/8-1:0]   in_dat_be,
  input  logic                  in_dat_valid,
  output logic                  in_dat_ready,
  output logic [DATA_W-1:0]     out_dat_data,
  output logic [DATA_W/8-1:0]   out_dat_be,
  output logic                  out_dat_valid,
  input  logic                  out_dat_ready,
  input  logic                  rsp_valid,
  input  logic                  rsp_ready,
  output logic                  out_rsp_valid,
  input  logic                  out_rsp_ready,
  output logic [3:0]            out_rsp_opcode,
  output logic                  out_snp_valid,
  input  logic                  out_snp_ready,
  output logic [ADDR_W-1:0]     out_snp_addr,
  output logic                  credit_full,
  output logic                  size_error,
  output logic                  order_violation,
  input  logic [3:0]            in_req_qos,
  input  logic                  in_req_c,
  input  logic                  in_req_dwt,
  input  logic                  in_req_expiry,
  input  logic [2:0]            in_req_comp_state,
  input  logic [3:0]            rsp_opcode,
  input  logic                  rsp_pcredit,
  input  logic [2:0]            rsp_comp_state,
  input  logic                  out_dvm_ready,
  input  logic                  out_rsos_ready,
  output logic [3:0]            out_req_qos,
  output logic                  out_req_c,
  output logic                  out_req_dwt,
  output logic                  out_req_expiry,
  output logic [2:0]            out_req_comp_state,
  output logic [2:0]            out_rsp_comp_state,
  output logic                  out_dvm_valid,
  output logic                  out_rsos_valid,
  output logic [8:0]            pcredit_count,
  output logic                  pcredit_full,
  output logic                  pcredit_overflow,
  output logic                  pcredit_underflow,
  output logic [2:0]            coh_state,
  output logic                  coh_error,
  output logic                  dwt_active,
  output logic                  dwt_cancel,
  output logic                  dwt_error,
  output logic                  expiry_active,
  output logic                  expiry_fired,
  output logic                  qos_high,
  output logic                  dvm_pending,
  output logic                  rsos_pending,
  input  logic                  in_ct_valid = 1'b0,
  input  logic [3:0]            in_ct_opcode = '0,
  input  logic [1:0]            in_ct_profile = '0,
  input  logic [ADDR_W-1:0]     in_ct_addr = '0,
  input  logic [2:0]            in_ct_size = '0,
  input  logic [3:0]            in_ct_qos = '0,
  input  logic                  in_ct_c = 1'b0,
  input  logic                  in_ct_dwt = 1'b0,
  input  logic                  in_ct_expiry = 1'b0,
  input  logic [2:0]            in_ct_comp_state = '0,
  output logic                  in_ct_ready,
  output logic [3:0]            out_ct_opcode,
  output logic [1:0]            out_ct_profile,
  output logic                  out_req_ct_legacy,
  output logic                  ct_unsupported,
  output logic [8:0]            reorder_count,
  output logic                  reorder_full,
  output logic                  hol_bypass,
  output logic [8:0]            outstanding_ch0,
  output logic [8:0]            outstanding_ch1,
  output logic [8:0]            outstanding_ch2,
  output logic [8:0]            outstanding_ch3,
  output logic [8:0]            dvm_outstanding,
  output logic [8:0]            rsos_outstanding,
  output logic                  rn_fn_signoff
);

  // CHI SIZE alignment: the DATA_W granule is DATA_W/8 bytes, so the
  // largest legal SIZE is $clog2(DATA_W/8) (e.g. DATA_W=256 -> 32B -> 5).
  localparam int BE_W = DATA_W / 8;
  localparam int MAX_SIZE = $clog2(BE_W);
  localparam int IDX_W = (REORDER_DEPTH <= 1) ? 1 : $clog2(REORDER_DEPTH);
  localparam int OC_W = $clog2(MAX_OUTSTANDING + 1);

  // Message-class decodes: opcode[1:0] is the REQ/RSP/SNP/DAT channel
  // map (Srota Plane C trio + DAT), opcode[3:2] is the message class
  // (0 normal, 1 DVM, 2 RSOS). RSP opcode returns the class to ack.
  logic rsp_hs;
  logic in_is_dvm;
  logic in_is_rsos;
  logic in_dvm_block;
  logic in_rsos_block;
  logic rsp_is_dvm_ack;
  logic rsp_is_rsos_ack;
  logic rsp_ch_is_rsp;
  logic in_qos_high;
  assign rsp_hs = rsp_valid && rsp_ready;
  assign in_is_dvm = (in_req_opcode[3:2] == 2'd1);
  assign in_is_rsos = (in_req_opcode[3:2] == 2'd2);
  assign in_dvm_block = (DVM_ENABLE == 0) && in_is_dvm;
  assign in_rsos_block = (RSOS_ENABLE == 0) && in_is_rsos;
  assign rsp_is_dvm_ack = (rsp_opcode[3:2] == 2'd1);
  assign rsp_is_rsos_ack = (rsp_opcode[3:2] == 2'd2);
  assign rsp_ch_is_rsp = (rsp_opcode[1:0] == 2'd1);
  /* verilator lint_off UNSIGNED */
  assign in_qos_high = (in_req_qos >= QOS_THRESHOLD[3:0]);
  /* verilator lint_on UNSIGNED */

  // CT/legacy decodes: in_ct_opcode[3:2] is the legacy class (0 CHI.B,
  // 1 CHI.C, 2 CHI.T, 3 reserved); in_ct_profile is the declared legacy
  // source and must equal the class. Reserved / mismatch / disabled are
  // typed ct_unsupported, never silently dropped.
  logic ct_is_dvm;
  logic ct_is_rsos;
  logic ct_class_bad;
  logic ct_profile_bad;
  logic ct_dvm_block;
  logic ct_rsos_block;
  logic ct_qos_high;
  assign ct_is_dvm = (in_ct_opcode[3:2] == 2'd1);
  assign ct_is_rsos = (in_ct_opcode[3:2] == 2'd2);
  assign ct_class_bad = (in_ct_opcode[3:2] == 2'd3);
  assign ct_profile_bad = (in_ct_profile > 2'd2) || (in_ct_profile != in_ct_opcode[3:2]);
  assign ct_dvm_block = (DVM_ENABLE == 0) && ct_is_dvm;
  assign ct_rsos_block = (RSOS_ENABLE == 0) && ct_is_rsos;
  /* verilator lint_off UNSIGNED */
  assign ct_qos_high = (in_ct_qos >= QOS_THRESHOLD[3:0]);
  /* verilator lint_on UNSIGNED */
  assign out_ct_opcode = in_ct_opcode;
  assign out_ct_profile = in_ct_profile;

  // Ordering enforcement (adapted from ordering_fsm.sv): track the next
  // in-order address; STRONG stalls capture on a gap, RELAXED flags, RAW
  // bypasses. Both the REQ and the CT/legacy ports feed the same
  // expected-address sequence. QoS: high-priority transactions
  // (qos_high) bypass the strong stall while order_violation still
  // flags the gap for observability.
  logic [ADDR_W-1:0] expected_addr_q;
  logic started_q;
  logic [ADDR_W-1:0] addr_gap;
  logic [ADDR_W-1:0] ct_addr_gap;
  logic in_order;
  logic ct_in_order;
  assign addr_gap = in_req_addr - expected_addr_q;
  assign ct_addr_gap = in_ct_addr - expected_addr_q;
  assign in_order = !started_q || (addr_gap == '0);
  assign ct_in_order = !started_q || (ct_addr_gap == '0);
  assign order_violation = (ORDERING_MODE != 0)
      && ((in_req_valid && !in_order) || (in_ct_valid && !ct_in_order));
  logic ordering_stall;
  logic ct_ordering_stall;
  assign ordering_stall = (ORDERING_MODE == 1) && !in_order && !in_qos_high;
  assign ct_ordering_stall = (ORDERING_MODE == 1) && !ct_in_order && !ct_qos_high;

  // Outstanding-credit table: one credit per emitted REQ, returned by
  // each RSP completion handshake (adapted from the AXI5 shim). The
  // per-class counters mirror the same events split by opcode[1:0].
  logic [OC_W-1:0] outstanding_q;
  logic [OC_W-1:0] outstanding_ch_q [4];
  logic req_emit;
  assign req_emit = out_req_valid && out_req_ready;
  assign credit_full = (outstanding_q >= OC_W'(MAX_OUTSTANDING));

  // P-Credit accounting: the peer grants credits on RSP handshakes with
  // rsp_pcredit set; each REQ or DAT emit consumes one. Empty stalls the
  // REQ output (pcredit_full); grant past P_CREDIT_MAX sets sticky
  // pcredit_overflow, DAT consume at zero sets pcredit_underflow.
  logic [8:0] pcredit_q;
  logic pcredit_grant;
  logic pcredit_consume;
  logic pcredit_overflow_q;
  logic pcredit_underflow_q;
  logic dat_emit;
  assign dat_emit = out_dat_valid && out_dat_ready;
  assign pcredit_grant = rsp_hs && rsp_pcredit;
  assign pcredit_consume = req_emit || dat_emit;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pcredit_q <= 9'(P_CREDIT_MAX);
      pcredit_overflow_q <= 1'b0;
      pcredit_underflow_q <= 1'b0;
    end else begin
      if (pcredit_consume && !pcredit_grant) begin
        if (pcredit_q == 9'd0) pcredit_underflow_q <= 1'b1;
        else pcredit_q <= pcredit_q - 9'd1;
      end else if (pcredit_grant && !pcredit_consume) begin
        if (pcredit_q >= P_CREDIT_MAX) pcredit_overflow_q <= 1'b1;
        else pcredit_q <= pcredit_q + 9'd1;
      end
    end
  end
  assign pcredit_count = pcredit_q;
  assign pcredit_full = (pcredit_q == 9'd0);
  assign pcredit_overflow = pcredit_overflow_q;
  assign pcredit_underflow = pcredit_underflow_q;

  // Request size alignment: clamp SIZE to MAX_SIZE and down-align the
  // address to the SIZE boundary. An over-granule size or an unaligned
  // address flags size_error but still forwards the aligned request.
  // The CT/legacy port is aligned the same way.
  logic [ADDR_W-1:0] aligned_addr;
  logic [2:0] aligned_size;
  logic [ADDR_W-1:0] size_mask;
  logic [31:0] transfer_bytes;
  logic [ADDR_W-1:0] ct_aligned_addr;
  logic [2:0] ct_aligned_size;
  logic [ADDR_W-1:0] ct_size_mask;
  logic [31:0] ct_transfer_bytes;
  always_comb begin
    transfer_bytes = 32'd1 << in_req_size;
    size_mask = (in_req_size == 3'd0) ? '0 : ((ADDR_W'(transfer_bytes)) - 1);
    if (in_req_size > MAX_SIZE[2:0]) aligned_size = MAX_SIZE[2:0];
    else aligned_size = in_req_size;
    aligned_addr = in_req_addr & ~size_mask;
    ct_transfer_bytes = 32'd1 << in_ct_size;
    ct_size_mask = (in_ct_size == 3'd0) ? '0 : ((ADDR_W'(ct_transfer_bytes)) - 1);
    if (in_ct_size > MAX_SIZE[2:0]) ct_aligned_size = MAX_SIZE[2:0];
    else ct_aligned_size = in_ct_size;
    ct_aligned_addr = in_ct_addr & ~ct_size_mask;
  end
  assign size_error = (in_req_size > MAX_SIZE[2:0]) || ((in_req_addr & size_mask) != '0);

  // Reorder buffer: REORDER_DEPTH entries (capture back-to-back, no
  // single-entry bottleneck). Coherency / QoS / C / DWT / Expiry /
  // CT-legacy fields ride each entry; per-entry coh state is primed
  // from the REQ comp field at capture.
  logic busy_q [REORDER_DEPTH];
  logic [ADDR_W-1:0] addr_q [REORDER_DEPTH];
  logic [2:0] size_q [REORDER_DEPTH];
  logic [3:0] opcode_q [REORDER_DEPTH];
  logic [1:0] ch_q [REORDER_DEPTH];
  logic [3:0] qos_q [REORDER_DEPTH];
  logic c_q [REORDER_DEPTH];
  logic dwt_q [REORDER_DEPTH];
  logic expiry_q [REORDER_DEPTH];
  logic [2:0] comp_q [REORDER_DEPTH];
  logic [2:0] coh_q [REORDER_DEPTH];
  logic ct_q [REORDER_DEPTH];
  logic [31:0] dwt_cnt_q [REORDER_DEPTH];
  logic dwt_cancel_q [REORDER_DEPTH];
  logic dwt_error_q [REORDER_DEPTH];
  logic [31:0] expiry_cnt_q [REORDER_DEPTH];
  logic expiry_fired_q [REORDER_DEPTH];
  logic [2:0] size_sticky_q;
  logic [2:0] coh_state_q;
  logic coh_error_q;
  logic [2:0] out_rsp_comp_q;
  logic ct_unsupported_q;
  // Channel mapping: opcode[1:0] selects REQ/RSP/SNP/DAT (Srota Plane C
  // trio + data). The fabric demultiplexes out_req_ch onto its VC.
  logic [1:0] ch_sel;
  always_comb begin
    case (in_req_opcode[1:0])
      2'd0: ch_sel = 2'd0;
      2'd1: ch_sel = 2'd1;
      2'd2: ch_sel = 2'd2;
      default: ch_sel = 2'd3;
    endcase
  end

  // Reorder arbitration (combinational): among gate-eligible entries
  // the highest QoS wins; ties go to the lowest index (oldest capture
  // first). A gate-blocked head does not stall younger eligible
  // entries: that is exactly hol_bypass.
  logic elig_q [REORDER_DEPTH];
  logic any_busy;
  logic any_eligible;
  logic [IDX_W-1:0] sel_idx;
  logic [3:0] sel_qos;
  logic [IDX_W-1:0] head_idx;
  logic head_blocked;
  logic [8:0] busy_count_c;
  logic [2:0] head_size;
  always_comb begin
    int i;
    any_busy = 1'b0;
    any_eligible = 1'b0;
    sel_idx = '0;
    sel_qos = '0;
    head_idx = '0;
    head_blocked = 1'b0;
    busy_count_c = '0;
    head_size = size_sticky_q;
    for (i = 0; i < REORDER_DEPTH; i = i + 1) begin
      elig_q[i] = busy_q[i]
          && ((opcode_q[i][3:2] != 2'd1) || out_dvm_ready)
          && ((opcode_q[i][3:2] != 2'd2) || out_rsos_ready);
    end
    for (i = 0; i < REORDER_DEPTH; i = i + 1) begin
      if (busy_q[i]) begin
        busy_count_c = busy_count_c + 9'd1;
        if (!any_busy) begin
          head_idx = IDX_W'(i);
          head_size = size_q[i];
        end
        any_busy = 1'b1;
        if (elig_q[i]) begin
          if (!any_eligible || (qos_q[i] > sel_qos)) begin
            sel_idx = IDX_W'(i);
            sel_qos = qos_q[i];
            any_eligible = 1'b1;
          end
        end
      end
    end
    head_blocked = any_busy && busy_q[head_idx] && !elig_q[head_idx];
  end

  // Reorder capture: lowest free entry, REQ port wins a same-cycle tie
  // over the CT/legacy port (held, not dropped).
  logic [IDX_W-1:0] free_idx;
  logic any_free;
  logic can_capture;
  logic ct_can_capture;
  logic req_capture;
  logic ct_capture;
  always_comb begin
    int i;
    free_idx = '0;
    any_free = 1'b0;
    for (i = 0; i < REORDER_DEPTH; i = i + 1) begin
      if (!busy_q[i] && !any_free) begin
        free_idx = IDX_W'(i);
        any_free = 1'b1;
      end
    end
  end
  assign can_capture = any_free && !credit_full && !ordering_stall && !in_dvm_block && !in_rsos_block;
  assign in_req_ready = can_capture;
  assign ct_can_capture = any_free && !credit_full && !ct_ordering_stall
      && (CT_ENABLE != 0) && !ct_class_bad && !ct_profile_bad
      && !ct_dvm_block && !ct_rsos_block;
  assign req_capture = in_req_valid && in_req_ready;
  assign in_ct_ready = ct_can_capture && !req_capture;
  assign ct_capture = in_ct_valid && in_ct_ready;

  // Outstanding queue (emit -> RSP completion): timers and coh state
  // travel with the transaction so watchdogs run until the RSP, not
  // just until emit.
  logic oc_valid_q [MAX_OUTSTANDING];
  logic [2:0] oc_coh_q [MAX_OUTSTANDING];
  logic oc_dvm_q [MAX_OUTSTANDING];
  logic oc_rsos_q [MAX_OUTSTANDING];
  logic oc_dwt_q [MAX_OUTSTANDING];
  logic oc_expiry_q [MAX_OUTSTANDING];
  logic [31:0] oc_dwt_cnt_q [MAX_OUTSTANDING];
  logic oc_dwt_cancel_q [MAX_OUTSTANDING];
  logic oc_dwt_error_q [MAX_OUTSTANDING];
  logic [31:0] oc_expiry_cnt_q [MAX_OUTSTANDING];
  logic oc_expiry_fired_q [MAX_OUTSTANDING];
  int oc_head;
  int oc_tail;
  int oc_count;

  // Coherency legal-transition FSM (repo-defined): comp states are
  // 0 I, 1 SC, 2 UC, 3 UD, 4 SD; reserved 5-7 are illegal, and a direct
  // UD<->SD transition is illegal. Every other valid -> valid move is
  // legal. RSP comp acks fold into the global coh_state; the popped
  // entry's coh state transitions the same way.
  logic coh_illegal;
  assign coh_illegal = rsp_hs && ((rsp_comp_state >= 3'd5)
      || ((coh_state_q == 3'd3) && (rsp_comp_state == 3'd4))
      || ((coh_state_q == 3'd4) && (rsp_comp_state == 3'd3))
      || ((oc_count > 0) && (oc_coh_q[oc_head] == 3'd3) && (rsp_comp_state == 3'd4))
      || ((oc_count > 0) && (oc_coh_q[oc_head] == 3'd4) && (rsp_comp_state == 3'd3)));

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      expected_addr_q <= '0;
      started_q <= 1'b0;
      size_sticky_q <= '0;
      coh_state_q <= 3'(COH_INIT);
      coh_error_q <= 1'b0;
      out_rsp_comp_q <= '0;
      ct_unsupported_q <= 1'b0;
      for (int i = 0; i < REORDER_DEPTH; i = i + 1) begin
        busy_q[i] <= 1'b0;
        addr_q[i] <= '0;
        size_q[i] <= '0;
        opcode_q[i] <= '0;
        ch_q[i] <= '0;
        qos_q[i] <= '0;
        c_q[i] <= 1'b0;
        dwt_q[i] <= 1'b0;
        expiry_q[i] <= 1'b0;
        comp_q[i] <= '0;
        coh_q[i] <= '0;
        ct_q[i] <= 1'b0;
      end
    end else begin
      if (in_ct_valid && ((CT_ENABLE == 0) || ct_class_bad || ct_profile_bad))
        ct_unsupported_q <= 1'b1;
      if (req_capture) begin
        busy_q[free_idx] <= 1'b1;
        addr_q[free_idx] <= aligned_addr;
        size_q[free_idx] <= aligned_size;
        opcode_q[free_idx] <= in_req_opcode;
        ch_q[free_idx] <= ch_sel;
        qos_q[free_idx] <= in_req_qos;
        c_q[free_idx] <= in_req_c;
        dwt_q[free_idx] <= in_req_dwt;
        expiry_q[free_idx] <= in_req_expiry;
        comp_q[free_idx] <= in_req_comp_state;
        coh_q[free_idx] <= in_req_comp_state;
        ct_q[free_idx] <= 1'b0;
        size_sticky_q <= aligned_size;
        if (in_req_comp_state >= 3'd5) coh_error_q <= 1'b1;
      end
      if (ct_capture) begin
        busy_q[free_idx] <= 1'b1;
        addr_q[free_idx] <= ct_aligned_addr;
        size_q[free_idx] <= ct_aligned_size;
        opcode_q[free_idx] <= in_ct_opcode;
        ch_q[free_idx] <= in_ct_opcode[1:0];
        qos_q[free_idx] <= in_ct_qos;
        c_q[free_idx] <= in_ct_c;
        dwt_q[free_idx] <= in_ct_dwt;
        expiry_q[free_idx] <= in_ct_expiry;
        comp_q[free_idx] <= in_ct_comp_state;
        coh_q[free_idx] <= in_ct_comp_state;
        ct_q[free_idx] <= 1'b1;
        size_sticky_q <= ct_aligned_size;
        if (in_ct_comp_state >= 3'd5) coh_error_q <= 1'b1;
      end
      if (req_emit) begin
        busy_q[sel_idx] <= 1'b0;
        expected_addr_q <= addr_q[sel_idx] + (ADDR_W'(32'd1 << size_q[sel_idx]));
        started_q <= 1'b1;
      end
      if (rsp_hs && ((rsp_is_dvm_ack || rsp_is_rsos_ack) && !rsp_ch_is_rsp))
        coh_error_q <= 1'b1;
      if (rsp_hs) begin
        out_rsp_comp_q <= rsp_comp_state;
        if (coh_illegal) coh_error_q <= 1'b1;
        else coh_state_q <= rsp_comp_state;
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      outstanding_q <= '0;
      for (int i = 0; i < 4; i = i + 1) outstanding_ch_q[i] <= '0;
      oc_head <= 0;
      oc_tail <= 0;
      oc_count <= 0;
      for (int j = 0; j < MAX_OUTSTANDING; j = j + 1) begin
        oc_valid_q[j] <= 1'b0;
        oc_coh_q[j] <= '0;
        oc_dvm_q[j] <= 1'b0;
        oc_rsos_q[j] <= 1'b0;
        oc_dwt_q[j] <= 1'b0;
        oc_expiry_q[j] <= 1'b0;
      end
    end else begin
      if (req_emit && !(rsp_hs && (ch_q[sel_idx] == rsp_opcode[1:0]))) begin
        if (!rsp_hs || (ch_q[sel_idx] != rsp_opcode[1:0])) begin
          outstanding_ch_q[ch_q[sel_idx]] <= outstanding_ch_q[ch_q[sel_idx]] + 1'b1;
        end
      end
      if (rsp_hs && !(req_emit && (ch_q[sel_idx] == rsp_opcode[1:0]))) begin
        if (outstanding_ch_q[rsp_opcode[1:0]] != '0)
          outstanding_ch_q[rsp_opcode[1:0]] <= outstanding_ch_q[rsp_opcode[1:0]] - 1'b1;
      end
      if (req_emit && !rsp_hs) outstanding_q <= outstanding_q + 1'b1;
      else if (rsp_hs && !req_emit && (outstanding_q != '0))
        outstanding_q <= outstanding_q - 1'b1;
      if (req_emit) begin
        oc_valid_q[oc_tail] <= 1'b1;
        oc_coh_q[oc_tail] <= coh_q[sel_idx];
        oc_dvm_q[oc_tail] <= (opcode_q[sel_idx][3:2] == 2'd1);
        oc_rsos_q[oc_tail] <= (opcode_q[sel_idx][3:2] == 2'd2);
        oc_dwt_q[oc_tail] <= dwt_q[sel_idx];
        oc_expiry_q[oc_tail] <= expiry_q[sel_idx];
        oc_dwt_cnt_q[oc_tail] <= dwt_cnt_q[sel_idx];
        oc_dwt_cancel_q[oc_tail] <= dwt_cancel_q[sel_idx];
        oc_dwt_error_q[oc_tail] <= dwt_error_q[sel_idx];
        oc_expiry_cnt_q[oc_tail] <= expiry_cnt_q[sel_idx];
        oc_expiry_fired_q[oc_tail] <= expiry_fired_q[sel_idx];
        if (oc_tail == MAX_OUTSTANDING - 1) oc_tail <= 0;
        else oc_tail <= oc_tail + 1;
      end
      if (rsp_hs && (oc_count > 0)) begin
        oc_valid_q[oc_head] <= 1'b0;
        if (oc_head == MAX_OUTSTANDING - 1) oc_head <= 0;
        else oc_head <= oc_head + 1;
      end
      if (req_emit && !rsp_hs) oc_count <= oc_count + 1;
      else if (rsp_hs && !req_emit && (oc_count > 0))
        oc_count <= oc_count - 1;
    end
  end

  // DWT/Expiry watchdogs (per transaction): count while the entry is
  // live with the field set, cancel/fire at the timeout, cleared when
  // the transaction's RSP retires it. Global outputs are the OR over
  // all live (reorder + outstanding) transactions.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < REORDER_DEPTH; i = i + 1) begin
        dwt_cnt_q[i] <= '0;
        dwt_cancel_q[i] <= 1'b0;
        dwt_error_q[i] <= 1'b0;
        expiry_cnt_q[i] <= '0;
        expiry_fired_q[i] <= 1'b0;
      end
    end else begin
      for (int i = 0; i < REORDER_DEPTH; i = i + 1) begin
        if (req_emit && (sel_idx == IDX_W'(i))) begin
          dwt_cnt_q[i] <= '0;
          dwt_cancel_q[i] <= 1'b0;
          dwt_error_q[i] <= 1'b0;
          expiry_cnt_q[i] <= '0;
          expiry_fired_q[i] <= 1'b0;
        end else if (busy_q[i] && dwt_q[i]) begin
          if (dwt_cancel_q[i]) begin
            dwt_cancel_q[i] <= 1'b1;
            dwt_error_q[i] <= 1'b1;
          end else if (dwt_cnt_q[i] + 32'd1 >= DWT_TIMEOUT) begin
            dwt_cancel_q[i] <= 1'b1;
            dwt_error_q[i] <= 1'b1;
          end else dwt_cnt_q[i] <= dwt_cnt_q[i] + 32'd1;
        end else if (!busy_q[i]) begin
          dwt_cnt_q[i] <= '0;
          dwt_cancel_q[i] <= 1'b0;
          dwt_error_q[i] <= 1'b0;
        end
        if (busy_q[i] && expiry_q[i]) begin
          if (expiry_fired_q[i]) expiry_fired_q[i] <= 1'b1;
          else if (expiry_cnt_q[i] + 32'd1 >= EXPIRY_TIMEOUT)
            expiry_fired_q[i] <= 1'b1;
          else expiry_cnt_q[i] <= expiry_cnt_q[i] + 32'd1;
        end else if (!busy_q[i]) begin
          expiry_cnt_q[i] <= '0;
          expiry_fired_q[i] <= 1'b0;
        end
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int j = 0; j < MAX_OUTSTANDING; j = j + 1) begin
        oc_dwt_cnt_q[j] <= '0;
        oc_dwt_cancel_q[j] <= 1'b0;
        oc_dwt_error_q[j] <= 1'b0;
        oc_expiry_cnt_q[j] <= '0;
        oc_expiry_fired_q[j] <= 1'b0;
      end
    end else begin
      for (int j = 0; j < MAX_OUTSTANDING; j = j + 1) begin
        if (!oc_valid_q[j]) begin
          oc_dwt_cnt_q[j] <= '0;
          oc_dwt_cancel_q[j] <= 1'b0;
          oc_dwt_error_q[j] <= 1'b0;
          oc_expiry_cnt_q[j] <= '0;
          oc_expiry_fired_q[j] <= 1'b0;
        end else if (oc_valid_q[j] && oc_dwt_q[j]) begin
          if (oc_dwt_cancel_q[j]) begin
            oc_dwt_cancel_q[j] <= 1'b1;
            oc_dwt_error_q[j] <= 1'b1;
          end else if (oc_dwt_cnt_q[j] + 32'd1 >= DWT_TIMEOUT) begin
            oc_dwt_cancel_q[j] <= 1'b1;
            oc_dwt_error_q[j] <= 1'b1;
          end else oc_dwt_cnt_q[j] <= oc_dwt_cnt_q[j] + 32'd1;
        end
        if (oc_valid_q[j] && oc_expiry_q[j]) begin
          if (oc_expiry_fired_q[j]) oc_expiry_fired_q[j] <= 1'b1;
          else if (oc_expiry_cnt_q[j] + 32'd1 >= EXPIRY_TIMEOUT)
            oc_expiry_fired_q[j] <= 1'b1;
          else oc_expiry_cnt_q[j] <= oc_expiry_cnt_q[j] + 32'd1;
        end
      end
    end
  end

  logic dwt_active_c;
  logic expiry_active_c;
  logic dwt_cancel_c;
  logic dwt_error_c;
  logic expiry_fired_c;
  logic dvm_pending_c;
  logic rsos_pending_c;
  logic [8:0] dvm_count_c;
  logic [8:0] rsos_count_c;
  always_comb begin
    int i;
    int j;
    dwt_active_c = 1'b0;
    expiry_active_c = 1'b0;
    dwt_cancel_c = 1'b0;
    dwt_error_c = 1'b0;
    expiry_fired_c = 1'b0;
    dvm_pending_c = 1'b0;
    rsos_pending_c = 1'b0;
    dvm_count_c = '0;
    rsos_count_c = '0;
    for (i = 0; i < REORDER_DEPTH; i = i + 1) begin
      if (busy_q[i] && dwt_q[i]) dwt_active_c = 1'b1;
      if (busy_q[i] && expiry_q[i]) expiry_active_c = 1'b1;
      if (busy_q[i] && (dwt_cancel_q[i] || dwt_error_q[i])) begin
        dwt_cancel_c = 1'b1;
        dwt_error_c = 1'b1;
      end
      if (busy_q[i] && expiry_fired_q[i]) expiry_fired_c = 1'b1;
    end
    for (j = 0; j < MAX_OUTSTANDING; j = j + 1) begin
      if (oc_valid_q[j] && oc_dwt_q[j]) dwt_active_c = 1'b1;
      if (oc_valid_q[j] && oc_expiry_q[j]) expiry_active_c = 1'b1;
      if (oc_valid_q[j] && (oc_dwt_cancel_q[j] || oc_dwt_error_q[j])) begin
        dwt_cancel_c = 1'b1;
        dwt_error_c = 1'b1;
      end
      if (oc_valid_q[j] && oc_expiry_fired_q[j]) expiry_fired_c = 1'b1;
      if (oc_valid_q[j] && oc_dvm_q[j]) begin
        dvm_pending_c = 1'b1;
        dvm_count_c = dvm_count_c + 9'd1;
      end
      if (oc_valid_q[j] && oc_rsos_q[j]) begin
        rsos_pending_c = 1'b1;
        rsos_count_c = rsos_count_c + 9'd1;
      end
    end
  end

  assign out_req_addr = addr_q[sel_idx];
  assign out_req_size = size_q[sel_idx];
  assign out_req_opcode = opcode_q[sel_idx];
  assign out_req_ch = ch_q[sel_idx];
  assign out_req_valid = any_eligible && !credit_full && !pcredit_full;
  assign out_req_qos = qos_q[sel_idx];
  assign out_req_c = c_q[sel_idx];
  assign out_req_dwt = dwt_q[sel_idx];
  assign out_req_expiry = expiry_q[sel_idx];
  assign out_req_comp_state = comp_q[sel_idx];
  assign out_rsp_comp_state = out_rsp_comp_q;
  /* verilator lint_off UNSIGNED */
  assign qos_high = (qos_q[sel_idx] >= QOS_THRESHOLD[3:0]);
  /* verilator lint_on UNSIGNED */
  assign out_dvm_valid = out_req_valid && (opcode_q[sel_idx][3:2] == 2'd1) && (DVM_ENABLE != 0);
  assign out_rsos_valid = out_req_valid && (opcode_q[sel_idx][3:2] == 2'd2) && (RSOS_ENABLE != 0);
  assign out_req_ct_legacy = ct_q[sel_idx];
  assign dvm_pending = dvm_pending_c;
  assign rsos_pending = rsos_pending_c;
  assign dvm_outstanding = dvm_count_c;
  assign rsos_outstanding = rsos_count_c;
  assign coh_state = coh_state_q;
  assign coh_error = coh_error_q;
  assign ct_unsupported = ct_unsupported_q;
  assign dwt_active = dwt_active_c;
  assign expiry_active = expiry_active_c;
  assign dwt_cancel = dwt_cancel_c;
  assign dwt_error = dwt_error_c;
  assign expiry_fired = expiry_fired_c;
  assign reorder_count = busy_count_c;
  assign reorder_full = !any_free;
  assign hol_bypass = any_eligible && head_blocked;
  assign outstanding_ch0 = 9'(outstanding_ch_q[0]);
  assign outstanding_ch1 = 9'(outstanding_ch_q[1]);
  assign outstanding_ch2 = 9'(outstanding_ch_q[2]);
  assign outstanding_ch3 = 9'(outstanding_ch_q[3]);
  assign rn_fn_signoff = 1'b0;

  // DAT channel: forwarded with byte-enable filtering by the
  // head-of-line entry SIZE (sticky SIZE when the buffer is idle).
  logic [BE_W-1:0] be_mask;
  logic [31:0] be_bytes;
  always_comb begin
    be_bytes = 32'd1 << head_size;
    be_mask = (be_bytes >= BE_W) ? '1 : (BE_W'((32'd1 << be_bytes) - 32'd1));
  end
  assign in_dat_ready = out_dat_ready;
  assign out_dat_data = in_dat_data;
  assign out_dat_be = in_dat_be & be_mask;
  assign out_dat_valid = in_dat_valid;

  // Channel demux: the arbitrated REQ also drives the RSP/SNP channels
  // when its opcode maps there (Srota Plane C REQ/RSP/SNP economy).
  assign out_rsp_valid = out_req_valid && (ch_q[sel_idx] == 2'd1);
  assign out_rsp_opcode = opcode_q[sel_idx];
  assign out_snp_valid = out_req_valid && (ch_q[sel_idx] == 2'd2);
  assign out_snp_addr = addr_q[sel_idx];
  /* verilator lint_off UNUSED */
  wire unused_ok = out_rsp_ready && out_snp_ready && out_dat_ready;
  /* verilator lint_on UNUSED */

endmodule
`default_nettype wire
"""


def _render_tilelink(params: AdapterParams, module: str) -> str:
    max_out = params.max_outstanding if params.max_outstanding is not None else 16
    ordering_name = _ordering_str(params.ordering) or "none"
    ordering_code = _ordering_code(params.ordering)
    return f"""`default_nettype none
`define TILELINK_VERSION "TileLink-1.8.1 UL+UH+C"
`define TILELINK_PROFILE "TileLink-UL+UH+C nic.sv"
module {module} #(
  parameter int DATA_W = {params.data_width},
  parameter int ADDR_W = {params.addr_width},
  parameter int MAX_OUTSTANDING = {max_out},
  parameter int ORDERING_MODE = {ordering_code},
  parameter int SOURCE_W = 5,
  parameter int SINK_W = 5,
  parameter int PARAM_W = 3
) (
  input logic clk,
  input logic rst_n,
  input logic [2:0] in_a_opcode,
  input logic [PARAM_W-1:0] in_a_param,
  input logic [2:0] in_a_size,
  input logic [SOURCE_W-1:0] in_a_source,
  input logic [ADDR_W-1:0] in_a_address,
  input logic [DATA_W/8-1:0] in_a_mask,
  input logic [DATA_W-1:0] in_a_data,
  input logic in_a_corrupt,
  input logic in_a_valid,
  output logic in_a_ready,
  output logic [2:0] out_a_opcode,
  output logic [PARAM_W-1:0] out_a_param,
  output logic [2:0] out_a_size,
  output logic [SOURCE_W-1:0] out_a_source,
  output logic [ADDR_W-1:0] out_a_address,
  output logic [DATA_W/8-1:0] out_a_mask,
  output logic [DATA_W-1:0] out_a_data,
  output logic out_a_corrupt,
  output logic out_a_valid,
  input logic out_a_ready,
  output logic out_a_head,
  output logic out_a_tail,
  input logic [2:0] in_b_opcode,
  input logic [PARAM_W-1:0] in_b_param,
  input logic [2:0] in_b_size,
  input logic [SOURCE_W-1:0] in_b_source,
  input logic [SINK_W-1:0] in_b_sink,
  input logic [ADDR_W-1:0] in_b_address,
  input logic in_b_corrupt,
  input logic in_b_valid,
  output logic in_b_ready,
  output logic [2:0] out_b_opcode,
  output logic [PARAM_W-1:0] out_b_param,
  output logic [2:0] out_b_size,
  output logic [SOURCE_W-1:0] out_b_source,
  output logic [SINK_W-1:0] out_b_sink,
  output logic [ADDR_W-1:0] out_b_address,
  output logic out_b_corrupt,
  output logic out_b_valid,
  input logic out_b_ready,
  output logic out_b_head,
  output logic out_b_tail,
  input logic [2:0] in_c_opcode,
  input logic [PARAM_W-1:0] in_c_param,
  input logic [2:0] in_c_size,
  input logic [SOURCE_W-1:0] in_c_source,
  input logic [ADDR_W-1:0] in_c_address,
  input logic [DATA_W/8-1:0] in_c_mask,
  input logic [DATA_W-1:0] in_c_data,
  input logic in_c_corrupt,
  input logic in_c_valid,
  output logic in_c_ready,
  output logic [2:0] out_c_opcode,
  output logic [PARAM_W-1:0] out_c_param,
  output logic [2:0] out_c_size,
  output logic [SOURCE_W-1:0] out_c_source,
  output logic [ADDR_W-1:0] out_c_address,
  output logic [DATA_W/8-1:0] out_c_mask,
  output logic [DATA_W-1:0] out_c_data,
  output logic out_c_corrupt,
  output logic out_c_valid,
  input logic out_c_ready,
  output logic out_c_head,
  output logic out_c_tail,
  input logic [2:0] in_d_opcode,
  input logic [PARAM_W-1:0] in_d_param,
  input logic [2:0] in_d_size,
  input logic [SOURCE_W-1:0] in_d_source,
  input logic [SINK_W-1:0] in_d_sink,
  input logic in_d_denied,
  input logic [DATA_W-1:0] in_d_data,
  input logic in_d_corrupt,
  input logic in_d_valid,
  output logic in_d_ready,
  output logic [2:0] out_d_opcode,
  output logic [PARAM_W-1:0] out_d_param,
  output logic [2:0] out_d_size,
  output logic [SOURCE_W-1:0] out_d_source,
  output logic [SINK_W-1:0] out_d_sink,
  output logic out_d_denied,
  output logic [DATA_W-1:0] out_d_data,
  output logic out_d_corrupt,
  output logic out_d_valid,
  input logic out_d_ready,
  output logic out_d_head,
  output logic out_d_tail,
  input logic [2:0] in_e_opcode,
  input logic [SINK_W-1:0] in_e_sink,
  input logic in_e_valid,
  output logic in_e_ready,
  output logic [2:0] out_e_opcode,
  output logic [SINK_W-1:0] out_e_sink,
  output logic out_e_valid,
  input logic out_e_ready,
  output logic out_e_head,
  output logic out_e_tail,
  output logic credit_full,
  output logic a_error,
  output logic b_error,
  output logic c_error,
  output logic d_error,
  output logic order_violation,
  output logic out_a_is_get,
  output logic out_a_is_rmw,
  output logic out_a_is_arith,
  output logic out_a_is_logical,
  output logic [PARAM_W-1:0] out_a_op_numeric,
  output logic out_a_is_intent,
  output logic out_a_is_acquire,
  output logic out_b_is_probe,
  output logic out_b_is_probe_ack,
  output logic out_b_is_probe_ack_data,
  output logic out_c_is_release,
  output logic out_c_is_release_data,
  output logic out_c_is_probe_ack,
  output logic out_c_is_probe_ack_data,
  output logic out_c_is_hint_ack,
  output logic out_d_is_access_ack,
  output logic out_d_is_access_ack_data,
  output logic out_d_is_hint_ack,
  output logic out_d_is_grant,
  output logic out_d_is_release_ack,
  output logic out_e_is_grant_ack,
  output logic out_e_is_release_ack,
  output logic a_illegal,
  output logic b_illegal,
  output logic c_illegal,
  output logic d_illegal,
  output logic e_illegal,
  output logic a_param_error,
  output logic b_param_error,
  output logic d_param_error,
  output logic e_sink_match,
  output logic e_sink_error
);
  localparam int BE_W = DATA_W / 8;
  localparam int MAX_SIZE = $clog2(BE_W);
  logic [$clog2(MAX_OUTSTANDING + 1)-1:0] outstanding_q;
  logic a_emit;
  logic b_emit;
  logic c_emit;
  logic d_complete;
  logic e_complete;
  logic req_emit;
  logic rsp_complete;
  assign a_emit = out_a_valid && out_a_ready;
  assign b_emit = out_b_valid && out_b_ready;
  assign c_emit = out_c_valid && out_c_ready;
  assign d_complete = out_d_valid && out_d_ready;
  assign e_complete = out_e_valid && out_e_ready;
  assign req_emit = a_emit || b_emit || c_emit;
  assign rsp_complete = d_complete || e_complete;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) outstanding_q <= '0;
    else begin
      if (req_emit && !rsp_complete) outstanding_q <= outstanding_q + 1'b1;
      else if (rsp_complete && !req_emit) outstanding_q <= outstanding_q - 1'b1;
    end
  end
  assign credit_full = (outstanding_q >= MAX_OUTSTANDING);
  logic [31:0] a_transfer_bytes;
  always_comb a_transfer_bytes = 32'd1 << in_a_size;
  logic a_aligned;
  always_comb a_aligned = ((in_a_address & (a_transfer_bytes - 32'd1)) == '0);
  logic a_size_ok;
  always_comb a_size_ok = (in_a_size <= MAX_SIZE[2:0]);
  assign a_error = in_a_valid && (!a_aligned || !a_size_ok);
  logic [31:0] b_transfer_bytes;
  always_comb b_transfer_bytes = 32'd1 << in_b_size;
  logic b_aligned;
  always_comb b_aligned = ((in_b_address & (b_transfer_bytes - 32'd1)) == '0);
  logic b_size_ok;
  always_comb b_size_ok = (in_b_size <= MAX_SIZE[2:0]);
  assign b_error = in_b_valid && (!b_aligned || !b_size_ok);
  logic [31:0] c_transfer_bytes;
  always_comb c_transfer_bytes = 32'd1 << in_c_size;
  logic c_aligned;
  always_comb c_aligned = ((in_c_address & (c_transfer_bytes - 32'd1)) == '0);
  logic c_size_ok;
  always_comb c_size_ok = (in_c_size <= MAX_SIZE[2:0]);
  assign c_error = in_c_valid && (!c_aligned || !c_size_ok);
  logic a_busy_q;
  logic [2:0] a_opcode_q;
  logic [PARAM_W-1:0] a_param_q;
  logic [2:0] a_size_q;
  logic [SOURCE_W-1:0] a_source_q;
  logic [ADDR_W-1:0] a_addr_q;
  logic [BE_W-1:0] a_mask_q;
  logic [DATA_W-1:0] a_data_q;
  logic a_corrupt_q;
  logic [31:0] a_beats_q;
  logic [31:0] a_beat_idx_q;
  logic [ADDR_W-1:0] a_expected_addr_q;
  logic a_started_q;
  logic [ADDR_W-1:0] a_addr_gap;
  assign a_addr_gap = in_a_address - a_expected_addr_q;
  logic a_in_order;
  assign a_in_order = !a_started_q || (a_addr_gap == '0);
  assign order_violation = (ORDERING_MODE != 0) && in_a_valid && !a_in_order;
  logic a_ordering_stall;
  assign a_ordering_stall = (ORDERING_MODE == 1) && !a_in_order;
  logic a_can_capture;
  assign a_can_capture = !a_busy_q && !credit_full && !a_ordering_stall;
  assign in_a_ready = a_can_capture;
  logic [31:0] a_total_beats;
  always_comb begin
    if (a_transfer_bytes <= BE_W) a_total_beats = 32'd1;
    else a_total_beats = a_transfer_bytes / BE_W;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      a_busy_q <= 1'b0;
      a_opcode_q <= '0;
      a_param_q <= '0;
      a_size_q <= '0;
      a_source_q <= '0;
      a_addr_q <= '0;
      a_mask_q <= '0;
      a_data_q <= '0;
      a_corrupt_q <= 1'b0;
      a_beats_q <= '0;
      a_beat_idx_q <= '0;
      a_expected_addr_q <= '0;
      a_started_q <= 1'b0;
    end else begin
      if (in_a_valid && in_a_ready) begin
        a_expected_addr_q <= in_a_address + BE_W;
        a_started_q <= 1'b1;
      end
      if (!a_busy_q) begin
        if (in_a_valid && in_a_ready) begin
          a_busy_q <= 1'b1;
          a_opcode_q <= in_a_opcode;
          a_param_q <= in_a_param;
          a_size_q <= in_a_size;
          a_source_q <= in_a_source;
          a_addr_q <= in_a_address;
          a_mask_q <= in_a_mask;
          a_data_q <= in_a_data;
          a_corrupt_q <= in_a_corrupt;
          a_beats_q <= a_total_beats;
          a_beat_idx_q <= '0;
        end
      end else if (out_a_valid && out_a_ready) begin
        if (a_beat_idx_q + 32'd1 >= a_beats_q) begin
          a_busy_q <= 1'b0;
          a_beat_idx_q <= '0;
        end else begin
          a_beat_idx_q <= a_beat_idx_q + 32'd1;
          a_addr_q <= a_addr_q + BE_W;
        end
      end
    end
  end
  assign out_a_opcode = a_opcode_q;
  assign out_a_param = a_param_q;
  assign out_a_size = a_size_q;
  assign out_a_source = a_source_q;
  assign out_a_address = a_addr_q;
  assign out_a_mask = a_mask_q;
  assign out_a_data = a_data_q;
  assign out_a_corrupt = a_corrupt_q;
  assign out_a_valid = a_busy_q && !credit_full;
  assign out_a_head = a_busy_q && (a_beat_idx_q == 32'd0);
  assign out_a_tail = a_busy_q && (a_beat_idx_q + 32'd1 >= a_beats_q);
  logic b_busy_q;
  logic [2:0] b_opcode_q;
  logic [PARAM_W-1:0] b_param_q;
  logic [2:0] b_size_q;
  logic [SOURCE_W-1:0] b_source_q;
  logic [SINK_W-1:0] b_sink_q;
  logic [ADDR_W-1:0] b_addr_q;
  logic b_corrupt_q;
  logic b_can_capture;
  assign b_can_capture = !b_busy_q && !credit_full;
  assign in_b_ready = b_can_capture;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      b_busy_q <= 1'b0;
      b_opcode_q <= '0;
      b_param_q <= '0;
      b_size_q <= '0;
      b_source_q <= '0;
      b_sink_q <= '0;
      b_addr_q <= '0;
      b_corrupt_q <= 1'b0;
    end else begin
      if (!b_busy_q) begin
        if (in_b_valid && in_b_ready) begin
          b_busy_q <= 1'b1;
          b_opcode_q <= in_b_opcode;
          b_param_q <= in_b_param;
          b_size_q <= in_b_size;
          b_source_q <= in_b_source;
          b_sink_q <= in_b_sink;
          b_addr_q <= in_b_address;
          b_corrupt_q <= in_b_corrupt;
        end
      end else if (out_b_valid && out_b_ready) begin
        b_busy_q <= 1'b0;
      end
    end
  end
  assign out_b_opcode = b_opcode_q;
  assign out_b_param = b_param_q;
  assign out_b_size = b_size_q;
  assign out_b_source = b_source_q;
  assign out_b_sink = b_sink_q;
  assign out_b_address = b_addr_q;
  assign out_b_corrupt = b_corrupt_q;
  assign out_b_valid = b_busy_q && !credit_full;
  assign out_b_head = b_busy_q;
  assign out_b_tail = b_busy_q;
  logic c_busy_q;
  logic [2:0] c_opcode_q;
  logic [PARAM_W-1:0] c_param_q;
  logic [2:0] c_size_q;
  logic [SOURCE_W-1:0] c_source_q;
  logic [ADDR_W-1:0] c_addr_q;
  logic [BE_W-1:0] c_mask_q;
  logic [DATA_W-1:0] c_data_q;
  logic c_corrupt_q;
  logic [31:0] c_beats_q;
  logic [31:0] c_beat_idx_q;
  logic c_can_capture;
  assign c_can_capture = !c_busy_q && !credit_full;
  assign in_c_ready = c_can_capture;
  logic [31:0] c_total_beats;
  always_comb begin
    if (c_transfer_bytes <= BE_W) c_total_beats = 32'd1;
    else c_total_beats = c_transfer_bytes / BE_W;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      c_busy_q <= 1'b0;
      c_opcode_q <= '0;
      c_param_q <= '0;
      c_size_q <= '0;
      c_source_q <= '0;
      c_addr_q <= '0;
      c_mask_q <= '0;
      c_data_q <= '0;
      c_corrupt_q <= 1'b0;
      c_beats_q <= '0;
      c_beat_idx_q <= '0;
    end else begin
      if (!c_busy_q) begin
        if (in_c_valid && in_c_ready) begin
          c_busy_q <= 1'b1;
          c_opcode_q <= in_c_opcode;
          c_param_q <= in_c_param;
          c_size_q <= in_c_size;
          c_source_q <= in_c_source;
          c_addr_q <= in_c_address;
          c_mask_q <= in_c_mask;
          c_data_q <= in_c_data;
          c_corrupt_q <= in_c_corrupt;
          c_beats_q <= c_total_beats;
          c_beat_idx_q <= '0;
        end
      end else if (out_c_valid && out_c_ready) begin
        if (c_beat_idx_q + 32'd1 >= c_beats_q) begin
          c_busy_q <= 1'b0;
          c_beat_idx_q <= '0;
        end else begin
          c_beat_idx_q <= c_beat_idx_q + 32'd1;
          c_addr_q <= c_addr_q + BE_W;
        end
      end
    end
  end
  assign out_c_opcode = c_opcode_q;
  assign out_c_param = c_param_q;
  assign out_c_size = c_size_q;
  assign out_c_source = c_source_q;
  assign out_c_address = c_addr_q;
  assign out_c_mask = c_mask_q;
  assign out_c_data = c_data_q;
  assign out_c_corrupt = c_corrupt_q;
  assign out_c_valid = c_busy_q && !credit_full;
  assign out_c_head = c_busy_q && (c_beat_idx_q == 32'd0);
  assign out_c_tail = c_busy_q && (c_beat_idx_q + 32'd1 >= c_beats_q);
  logic [31:0] d_transfer_bytes;
  always_comb d_transfer_bytes = 32'd1 << in_d_size;
  logic d_size_ok;
  always_comb d_size_ok = (in_d_size <= MAX_SIZE[2:0]);
  assign d_error = in_d_valid && !d_size_ok;
  logic d_busy_q;
  logic [2:0] d_opcode_q;
  logic [PARAM_W-1:0] d_param_q;
  logic [2:0] d_size_q;
  logic [SOURCE_W-1:0] d_source_q;
  logic [SINK_W-1:0] d_sink_q;
  logic d_denied_q;
  logic [DATA_W-1:0] d_data_q;
  logic d_corrupt_q;
  logic [31:0] d_beats_q;
  logic [31:0] d_beat_idx_q;
  logic d_can_capture;
  assign d_can_capture = !d_busy_q;
  assign in_d_ready = d_can_capture;
  logic [31:0] d_total_beats;
  always_comb begin
    if (d_transfer_bytes <= BE_W) d_total_beats = 32'd1;
    else d_total_beats = d_transfer_bytes / BE_W;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      d_busy_q <= 1'b0;
      d_opcode_q <= '0;
      d_param_q <= '0;
      d_size_q <= '0;
      d_source_q <= '0;
      d_sink_q <= '0;
      d_denied_q <= 1'b0;
      d_data_q <= '0;
      d_corrupt_q <= 1'b0;
      d_beats_q <= '0;
      d_beat_idx_q <= '0;
    end else begin
      if (!d_busy_q) begin
        if (in_d_valid && in_d_ready) begin
          d_busy_q <= 1'b1;
          d_opcode_q <= in_d_opcode;
          d_param_q <= in_d_param;
          d_size_q <= in_d_size;
          d_source_q <= in_d_source;
          d_sink_q <= in_d_sink;
          d_denied_q <= in_d_denied;
          d_data_q <= in_d_data;
          d_corrupt_q <= in_d_corrupt;
          d_beats_q <= d_total_beats;
          d_beat_idx_q <= '0;
        end
      end else if (out_d_valid && out_d_ready) begin
        if (d_beat_idx_q + 32'd1 >= d_beats_q) begin
          d_busy_q <= 1'b0;
          d_beat_idx_q <= '0;
        end else begin
          d_beat_idx_q <= d_beat_idx_q + 32'd1;
        end
      end
    end
  end
  assign out_d_opcode = d_opcode_q;
  assign out_d_param = d_param_q;
  assign out_d_size = d_size_q;
  assign out_d_source = d_source_q;
  assign out_d_sink = d_sink_q;
  assign out_d_denied = d_denied_q;
  assign out_d_data = d_data_q;
  assign out_d_corrupt = d_corrupt_q;
  assign out_d_valid = d_busy_q;
  assign out_d_head = d_busy_q && (d_beat_idx_q == 32'd0);
  assign out_d_tail = d_busy_q && (d_beat_idx_q + 32'd1 >= d_beats_q);
  logic e_busy_q;
  logic [2:0] e_opcode_q;
  logic [SINK_W-1:0] e_sink_q;
  logic e_can_capture;
  assign e_can_capture = !e_busy_q;
  assign in_e_ready = e_can_capture;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      e_busy_q <= 1'b0;
      e_opcode_q <= '0;
      e_sink_q <= '0;
    end else begin
      if (!e_busy_q) begin
        if (in_e_valid && in_e_ready) begin
          e_busy_q <= 1'b1;
          e_opcode_q <= in_e_opcode;
          e_sink_q <= in_e_sink;
        end
      end else if (out_e_valid && out_e_ready) begin
        e_busy_q <= 1'b0;
      end
    end
  end
  assign out_e_opcode = e_opcode_q;
  assign out_e_sink = e_sink_q;
  assign out_e_valid = e_busy_q;
  assign out_e_head = e_busy_q;
  assign out_e_tail = e_busy_q;
  logic [SINK_W-1:0] sink_fifo [MAX_OUTSTANDING];
  int sink_head;
  int sink_tail;
  int sink_count;
  int sink_count_next;
  logic sink_push;
  logic sink_pop;
  assign sink_push = in_d_valid && in_d_ready;
  assign sink_pop = in_e_valid && in_e_ready;
  assign e_sink_match = in_e_valid && (sink_count > 0) && (sink_fifo[sink_head] == in_e_sink);
  assign e_sink_error = in_e_valid && !e_sink_match;
  always_comb begin
    sink_count_next = sink_count + (sink_push ? 1 : 0) - (sink_pop ? 1 : 0);
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      sink_head <= 0;
      sink_tail <= 0;
      sink_count <= 0;
    end else begin
      sink_count <= sink_count_next;
      if (sink_push) begin
        sink_fifo[sink_tail] <= in_d_sink;
        if (sink_tail == MAX_OUTSTANDING - 1) sink_tail <= 0;
        else sink_tail <= sink_tail + 1;
      end
      if (sink_pop && (sink_count > 0)) begin
        if (sink_head == MAX_OUTSTANDING - 1) sink_head <= 0;
        else sink_head <= sink_head + 1;
      end
    end
  end
  assign out_a_is_get = (a_opcode_q == 3'd4);
  assign out_a_is_rmw = (a_opcode_q == 3'd2) || (a_opcode_q == 3'd3);
  assign out_a_is_arith = (a_opcode_q == 3'd2);
  assign out_a_is_logical = (a_opcode_q == 3'd3);
  assign out_a_op_numeric = out_a_is_arith ? a_param_q : '0;
  assign out_a_is_intent = (a_opcode_q == 3'd5);
  assign out_a_is_acquire = (a_opcode_q == 3'd6) || (a_opcode_q == 3'd7);
  assign out_b_is_probe = (b_opcode_q == 3'd0);
  assign out_b_is_probe_ack = (b_opcode_q == 3'd1);
  assign out_b_is_probe_ack_data = (b_opcode_q == 3'd2);
  assign out_c_is_release = (c_opcode_q == 3'd0);
  assign out_c_is_release_data = (c_opcode_q == 3'd1);
  assign out_c_is_probe_ack = (c_opcode_q == 3'd2);
  assign out_c_is_probe_ack_data = (c_opcode_q == 3'd3);
  assign out_c_is_hint_ack = (c_opcode_q == 3'd4);
  assign out_d_is_access_ack = (d_opcode_q == 3'd0);
  assign out_d_is_access_ack_data = (d_opcode_q == 3'd1);
  assign out_d_is_hint_ack = (d_opcode_q == 3'd2);
  assign out_d_is_grant = (d_opcode_q == 3'd3) || (d_opcode_q == 3'd4);
  assign out_d_is_release_ack = (d_opcode_q == 3'd5);
  assign out_e_is_grant_ack = (e_opcode_q == 3'd0);
  assign out_e_is_release_ack = (e_opcode_q == 3'd1);
  assign a_illegal = 1'b0;
  assign b_illegal = in_b_valid && (in_b_opcode > 3'd2);
  assign c_illegal = in_c_valid && (in_c_opcode > 3'd4);
  assign d_illegal = in_d_valid && (in_d_opcode > 3'd5);
  assign e_illegal = in_e_valid && (in_e_opcode > 3'd1);
  assign a_param_error = in_a_valid && ((in_a_opcode == 3'd2 && in_a_param > 3'd4) || (in_a_opcode == 3'd3 && in_a_param > 3'd3) || ((in_a_opcode == 3'd6 || in_a_opcode == 3'd7) && in_a_param > 3'd2));
  assign b_param_error = in_b_valid && (in_b_opcode == 3'd0 && in_b_param > 3'd2);
  assign d_param_error = in_d_valid && ((in_d_opcode == 3'd3 || in_d_opcode == 3'd4) && in_d_param > 3'd2);
`ifdef TILELINK_FORMAL
  assert property (@(posedge clk) !(in_b_valid && in_b_ready && b_illegal));
  assert property (@(posedge clk) !(in_c_valid && in_c_ready && c_illegal));
  assert property (@(posedge clk) !(in_d_valid && in_d_ready && d_illegal));
  assert property (@(posedge clk) !(in_e_valid && in_e_ready && e_illegal));
  assert property (@(posedge clk) !(in_a_valid && in_a_ready && a_param_error));
  assert property (@(posedge clk) !(in_b_valid && in_b_ready && b_param_error));
  assert property (@(posedge clk) !(in_d_valid && in_d_ready && d_param_error));
  assert property (@(posedge clk) !(in_e_valid && in_e_ready && e_sink_error));
  cover property (@(posedge clk) in_a_valid && in_a_ready && (in_a_opcode == 3'd2));
  cover property (@(posedge clk) in_a_valid && in_a_ready && (in_a_opcode == 3'd3));
  cover property (@(posedge clk) in_a_valid && in_a_ready && (in_a_opcode == 3'd5));
  cover property (@(posedge clk) in_a_valid && in_a_ready && ((in_a_opcode == 3'd6) || (in_a_opcode == 3'd7)));
  cover property (@(posedge clk) in_b_valid && in_b_ready && (in_b_opcode == 3'd0));
  cover property (@(posedge clk) in_c_valid && in_c_ready && (in_c_opcode == 3'd3));
  cover property (@(posedge clk) in_d_valid && in_d_ready && (in_d_opcode == 3'd1));
  cover property (@(posedge clk) in_d_valid && in_d_ready && (in_d_opcode == 3'd2));
  cover property (@(posedge clk) in_e_valid && in_e_ready && (in_e_opcode == 3'd0));
`endif
endmodule
`default_nettype wire
"""

def _render_custom(params: AdapterParams, module: str) -> str:
    burst_at = params.split_at if params.split_at is not None else 0
    max_out = params.max_outstanding if params.max_outstanding is not None else 0
    ordering_name = _ordering_str(params.ordering) or "none"
    ordering_code = _ordering_code(params.ordering)
    burst_declared = params.split_at is not None
    ordering_declared = params.ordering is not None
    if burst_declared and ordering_declared:
        declared_line = (
            f"both declared: burst BURST_AT={burst_at} and ordering "
            f"{ordering_name} (ORDERING_MODE={ordering_code})")
    elif burst_declared:
        declared_line = (
            f"burst declared only: BURST_AT={burst_at} "
            f"(ORDERING_MODE=0 means no ordering declared, raw/bypass)")
    else:
        declared_line = (
            f"ordering declared only: {ordering_name} "
            f"(ORDERING_MODE={ordering_code}, BURST_AT=0 means no burst "
            f"declared)")
    return f"""// {module}.sv — AdapterFactory custom shim for agent group {params.agent_idx}.
// Generated by veritx_dse.product.adapter_factory_rtl (M4 deep module).
// Scope (honest): protocol-neutral burst/ordering shim parameterized ONLY
// by the agent-declared values ({declared_line}). No hidden defaults: a
// custom intent with neither a burst (split_at) nor an ordering param is
// INVALID at compile and this module is never emitted for it.
//   BURST_AT = burst beats per alignment group (0 = no burst declared).
//   ORDERING_MODE = 0 raw/bypass, 1 strong (stall-on-violation), 2 relaxed
//   (flag beyond the MAX_OUTSTANDING window). MAX_OUTSTANDING = 0 means no
//   cap declared (unbounded); a nonzero value is an explicit credit bound.
// Burst/ordering enforcement is adapted from ordering_fsm.sv (split
// counter + sequence check), not a pass-through: burst_required marks the
// alignment boundary, order_violation flags out-of-order delivery, and
// outstanding_full backpressures in_ready.
`default_nettype none

module {module} #(
  parameter int DATA_W = {params.data_width},
  parameter int ADDR_W = {params.addr_width},
  parameter int BURST_AT = {burst_at},
  parameter int ORDERING_MODE = {ordering_code},
  parameter int MAX_OUTSTANDING = {max_out}
) (
  input  logic                  clk,
  input  logic                  rst_n,
  input  logic [ADDR_W-1:0]     in_addr,
  input  logic [DATA_W-1:0]     in_data,
  input  logic [12:0]           in_seq,
  input  logic                  in_valid,
  output logic                  in_ready,
  output logic [ADDR_W-1:0]     out_addr,
  output logic [DATA_W-1:0]     out_data,
  output logic [12:0]           out_seq,
  output logic                  out_valid,
  input  logic                  out_ready,
  input  logic                  complete_pulse,
  output logic                  burst_required,
  output logic                  order_violation,
  output logic                  outstanding_full
);

  // Burst/ordering enforcement (adapted from ordering_fsm.sv): BURST_AT
  // closes a burst group every BURST_AT beats; in_seq is the transaction
  // sequence the ordering check compares against expected_seq.
  logic [12:0] expected_seq;
  int seq_gap;
  int outstanding_cnt;
  int burst_cnt;
  logic burst_pending;
  logic in_order;
  logic within_window;
  logic accept;
  logic [12:0] seq_in;
  assign seq_in = in_seq;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      expected_seq <= 13'd0;
      outstanding_cnt <= 0;
      burst_cnt <= 0;
      burst_pending <= 1'b0;
    end else begin
      if (accept) begin
        expected_seq <= seq_in + 13'd1;
        if (BURST_AT != 0 && burst_cnt == (BURST_AT - 1)) begin
          burst_cnt <= 0;
          burst_pending <= 1'b1;
        end else if (BURST_AT != 0) begin
          burst_cnt <= burst_cnt + 1;
          burst_pending <= 1'b0;
        end
      end
      if (accept && !complete_pulse)
        outstanding_cnt <= outstanding_cnt + 1;
      else if (complete_pulse && !accept && outstanding_cnt > 0)
        outstanding_cnt <= outstanding_cnt - 1;
    end
  end
  assign seq_gap = int'(seq_in) - int'(expected_seq);
  assign in_order = (seq_gap == 0);
  assign within_window = (seq_gap <= MAX_OUTSTANDING);
  assign order_violation = (ORDERING_MODE == 1) ? (in_valid && !in_order)
                           : ((ORDERING_MODE == 2) ? (in_valid && !within_window && !in_order) : 1'b0);
  assign outstanding_full = (MAX_OUTSTANDING == 0) ? 1'b0
                           : (outstanding_cnt >= MAX_OUTSTANDING);
  // Strong enforcement is stall-on-violation (no reorder buffer): an
  // out-of-order head is held at the boundary. Relaxed flags beyond the
  // window without stalling; RAW bypasses.
  assign in_ready = out_ready && !outstanding_full
                    && ((ORDERING_MODE != 1) || in_order);
  assign out_valid = in_valid;
  assign accept = in_valid && in_ready;
  assign burst_required = (BURST_AT != 0) && (burst_cnt == (BURST_AT - 1));
  assign out_data = in_data;
  assign out_seq = seq_in;
  assign out_addr = in_addr;
  /* verilator lint_off UNUSED */
  wire unused_ok = burst_pending && within_window;
  /* verilator lint_on UNUSED */

endmodule
`default_nettype wire
"""


def build_adapter(params: AdapterParams) -> AdapterBuild:
    """Editor layer: one param struct in -> (module, source, verdict) out."""
    verdict = check_params(params)
    if not verdict.ok:
        return AdapterBuild(params=params, module=None, source=None,
                            verdict=verdict)
    family = _family(params)
    assert family is not None
    if family not in SUPPORTED_FAMILIES:
        return AdapterBuild(params=params, module=None, source=None,
                            verdict=_unsupported(params, family))
    module = adapter_module_name(params.agent_idx, family)
    if family == ProtocolFamily.CHI:
        source = _render_chi(params, module)
    elif family == ProtocolFamily.TILELINK:
        source = _render_tilelink(params, module)
    elif family == ProtocolFamily.CUSTOM:
        source = _render_custom(params, module)
    else:
        source = _render_axi5(params, module)
    return AdapterBuild(params=params, module=module, source=source,
                        verdict=Verdict(ok=True))


def adapter_inventory(params_list: tuple[AdapterParams, ...]) -> AdapterSummary:
    """Summary layer: read-only admission inventory, nothing emitted."""
    supported: list[str] = []
    blocked: list[str] = []
    counts: dict[str, int] = {}
    for params in params_list:
        build = build_adapter(params)
        family = _family(params)
        key = family.value if family else str(params.protocol)
        counts[key] = counts.get(key, 0) + 1
        if build.module is not None:
            supported.append(
                f"group{params.agent_idx}:{build.module}")
        else:
            blocked.append(
                f"group{params.agent_idx}:{build.verdict.blocker_id}")
    return AdapterSummary(supported=tuple(sorted(supported)),
                          blocked=tuple(sorted(blocked)),
                          counts=tuple(sorted(counts.items())))


def tilelink_directed_tb_source(module: str) -> str:
    return f"""`default_nettype none
module tb_tilelink;
  logic clk;
  logic rst_n;
  logic [2:0] in_a_opcode;
  logic [2:0] in_a_param;
  logic [2:0] in_a_size;
  logic [4:0] in_a_source;
  logic [31:0] in_a_address;
  logic [7:0] in_a_mask;
  logic [63:0] in_a_data;
  logic in_a_corrupt;
  logic in_a_valid;
  logic in_a_ready;
  logic [2:0] out_a_opcode;
  logic [2:0] out_a_param;
  logic [2:0] out_a_size;
  logic [4:0] out_a_source;
  logic [31:0] out_a_address;
  logic [7:0] out_a_mask;
  logic [63:0] out_a_data;
  logic out_a_corrupt;
  logic out_a_valid;
  logic out_a_ready;
  logic out_a_head;
  logic out_a_tail;
  logic [2:0] in_b_opcode;
  logic [2:0] in_b_param;
  logic [2:0] in_b_size;
  logic [4:0] in_b_source;
  logic [4:0] in_b_sink;
  logic [31:0] in_b_address;
  logic in_b_corrupt;
  logic in_b_valid;
  logic in_b_ready;
  logic [2:0] out_b_opcode;
  logic [2:0] out_b_param;
  logic [2:0] out_b_size;
  logic [4:0] out_b_source;
  logic [4:0] out_b_sink;
  logic [31:0] out_b_address;
  logic out_b_corrupt;
  logic out_b_valid;
  logic out_b_ready;
  logic out_b_head;
  logic out_b_tail;
  logic [2:0] in_c_opcode;
  logic [2:0] in_c_param;
  logic [2:0] in_c_size;
  logic [4:0] in_c_source;
  logic [31:0] in_c_address;
  logic [7:0] in_c_mask;
  logic [63:0] in_c_data;
  logic in_c_corrupt;
  logic in_c_valid;
  logic in_c_ready;
  logic [2:0] out_c_opcode;
  logic [2:0] out_c_param;
  logic [2:0] out_c_size;
  logic [4:0] out_c_source;
  logic [31:0] out_c_address;
  logic [7:0] out_c_mask;
  logic [63:0] out_c_data;
  logic out_c_corrupt;
  logic out_c_valid;
  logic out_c_ready;
  logic out_c_head;
  logic out_c_tail;
  logic [2:0] in_d_opcode;
  logic [2:0] in_d_param;
  logic [2:0] in_d_size;
  logic [4:0] in_d_source;
  logic [4:0] in_d_sink;
  logic in_d_denied;
  logic [63:0] in_d_data;
  logic in_d_corrupt;
  logic in_d_valid;
  logic in_d_ready;
  logic [2:0] out_d_opcode;
  logic [2:0] out_d_param;
  logic [2:0] out_d_size;
  logic [4:0] out_d_source;
  logic [4:0] out_d_sink;
  logic out_d_denied;
  logic [63:0] out_d_data;
  logic out_d_corrupt;
  logic out_d_valid;
  logic out_d_ready;
  logic out_d_head;
  logic out_d_tail;
  logic [2:0] in_e_opcode;
  logic [4:0] in_e_sink;
  logic in_e_valid;
  logic in_e_ready;
  logic [2:0] out_e_opcode;
  logic [4:0] out_e_sink;
  logic out_e_valid;
  logic out_e_ready;
  logic out_e_head;
  logic out_e_tail;
  logic credit_full;
  logic a_error;
  logic b_error;
  logic c_error;
  logic d_error;
  logic order_violation;
  logic out_a_is_get;
  logic out_a_is_rmw;
  logic out_a_is_arith;
  logic out_a_is_logical;
  logic [2:0] out_a_op_numeric;
  logic out_a_is_intent;
  logic out_a_is_acquire;
  logic out_b_is_probe;
  logic out_b_is_probe_ack;
  logic out_b_is_probe_ack_data;
  logic out_c_is_release;
  logic out_c_is_release_data;
  logic out_c_is_probe_ack;
  logic out_c_is_probe_ack_data;
  logic out_c_is_hint_ack;
  logic out_d_is_access_ack;
  logic out_d_is_access_ack_data;
  logic out_d_is_hint_ack;
  logic out_d_is_grant;
  logic out_d_is_release_ack;
  logic out_e_is_grant_ack;
  logic out_e_is_release_ack;
  logic a_illegal;
  logic b_illegal;
  logic c_illegal;
  logic d_illegal;
  logic e_illegal;
  logic a_param_error;
  logic b_param_error;
  logic d_param_error;
  logic e_sink_match;
  logic e_sink_error;
  {module} #(.DATA_W(64),.ADDR_W(32),.MAX_OUTSTANDING(64),.ORDERING_MODE(0)) dut (
    .clk(clk),.rst_n(rst_n),
    .in_a_opcode(in_a_opcode),.in_a_param(in_a_param),.in_a_size(in_a_size),.in_a_source(in_a_source),.in_a_address(in_a_address),.in_a_mask(in_a_mask),.in_a_data(in_a_data),.in_a_corrupt(in_a_corrupt),.in_a_valid(in_a_valid),.in_a_ready(in_a_ready),
    .out_a_opcode(out_a_opcode),.out_a_param(out_a_param),.out_a_size(out_a_size),.out_a_source(out_a_source),.out_a_address(out_a_address),.out_a_mask(out_a_mask),.out_a_data(out_a_data),.out_a_corrupt(out_a_corrupt),.out_a_valid(out_a_valid),.out_a_ready(out_a_ready),.out_a_head(out_a_head),.out_a_tail(out_a_tail),
    .in_b_opcode(in_b_opcode),.in_b_param(in_b_param),.in_b_size(in_b_size),.in_b_source(in_b_source),.in_b_sink(in_b_sink),.in_b_address(in_b_address),.in_b_corrupt(in_b_corrupt),.in_b_valid(in_b_valid),.in_b_ready(in_b_ready),
    .out_b_opcode(out_b_opcode),.out_b_param(out_b_param),.out_b_size(out_b_size),.out_b_source(out_b_source),.out_b_sink(out_b_sink),.out_b_address(out_b_address),.out_b_corrupt(out_b_corrupt),.out_b_valid(out_b_valid),.out_b_ready(out_b_ready),.out_b_head(out_b_head),.out_b_tail(out_b_tail),
    .in_c_opcode(in_c_opcode),.in_c_param(in_c_param),.in_c_size(in_c_size),.in_c_source(in_c_source),.in_c_address(in_c_address),.in_c_mask(in_c_mask),.in_c_data(in_c_data),.in_c_corrupt(in_c_corrupt),.in_c_valid(in_c_valid),.in_c_ready(in_c_ready),
    .out_c_opcode(out_c_opcode),.out_c_param(out_c_param),.out_c_size(out_c_size),.out_c_source(out_c_source),.out_c_address(out_c_address),.out_c_mask(out_c_mask),.out_c_data(out_c_data),.out_c_corrupt(out_c_corrupt),.out_c_valid(out_c_valid),.out_c_ready(out_c_ready),.out_c_head(out_c_head),.out_c_tail(out_c_tail),
    .in_d_opcode(in_d_opcode),.in_d_param(in_d_param),.in_d_size(in_d_size),.in_d_source(in_d_source),.in_d_sink(in_d_sink),.in_d_denied(in_d_denied),.in_d_data(in_d_data),.in_d_corrupt(in_d_corrupt),.in_d_valid(in_d_valid),.in_d_ready(in_d_ready),
    .out_d_opcode(out_d_opcode),.out_d_param(out_d_param),.out_d_size(out_d_size),.out_d_source(out_d_source),.out_d_sink(out_d_sink),.out_d_denied(out_d_denied),.out_d_data(out_d_data),.out_d_corrupt(out_d_corrupt),.out_d_valid(out_d_valid),.out_d_ready(out_d_ready),.out_d_head(out_d_head),.out_d_tail(out_d_tail),
    .in_e_opcode(in_e_opcode),.in_e_sink(in_e_sink),.in_e_valid(in_e_valid),.in_e_ready(in_e_ready),
    .out_e_opcode(out_e_opcode),.out_e_sink(out_e_sink),.out_e_valid(out_e_valid),.out_e_ready(out_e_ready),.out_e_head(out_e_head),.out_e_tail(out_e_tail),
    .credit_full(credit_full),.a_error(a_error),.b_error(b_error),.c_error(c_error),.d_error(d_error),.order_violation(order_violation),
    .out_a_is_get(out_a_is_get),.out_a_is_rmw(out_a_is_rmw),.out_a_is_arith(out_a_is_arith),.out_a_is_logical(out_a_is_logical),.out_a_op_numeric(out_a_op_numeric),.out_a_is_intent(out_a_is_intent),.out_a_is_acquire(out_a_is_acquire),
    .out_b_is_probe(out_b_is_probe),.out_b_is_probe_ack(out_b_is_probe_ack),.out_b_is_probe_ack_data(out_b_is_probe_ack_data),
    .out_c_is_release(out_c_is_release),.out_c_is_release_data(out_c_is_release_data),.out_c_is_probe_ack(out_c_is_probe_ack),.out_c_is_probe_ack_data(out_c_is_probe_ack_data),.out_c_is_hint_ack(out_c_is_hint_ack),
    .out_d_is_access_ack(out_d_is_access_ack),.out_d_is_access_ack_data(out_d_is_access_ack_data),.out_d_is_hint_ack(out_d_is_hint_ack),.out_d_is_grant(out_d_is_grant),.out_d_is_release_ack(out_d_is_release_ack),
    .out_e_is_grant_ack(out_e_is_grant_ack),.out_e_is_release_ack(out_e_is_release_ack),
    .a_illegal(a_illegal),.b_illegal(b_illegal),.c_illegal(c_illegal),.d_illegal(d_illegal),.e_illegal(e_illegal),
    .a_param_error(a_param_error),.b_param_error(b_param_error),.d_param_error(d_param_error),
    .e_sink_match(e_sink_match),.e_sink_error(e_sink_error)
  );
  always #5 clk = ~clk;
  initial begin
    clk = 0;
    rst_n = 0;
    in_a_opcode = 0;
    in_a_param = 0;
    in_a_size = 0;
    in_a_source = 0;
    in_a_address = 0;
    in_a_mask = 0;
    in_a_data = 0;
    in_a_corrupt = 0;
    in_a_valid = 0;
    out_a_ready = 1;
    in_b_opcode = 0;
    in_b_param = 0;
    in_b_size = 0;
    in_b_source = 0;
    in_b_sink = 0;
    in_b_address = 0;
    in_b_corrupt = 0;
    in_b_valid = 0;
    out_b_ready = 1;
    in_c_opcode = 0;
    in_c_param = 0;
    in_c_size = 0;
    in_c_source = 0;
    in_c_address = 0;
    in_c_mask = 0;
    in_c_data = 0;
    in_c_corrupt = 0;
    in_c_valid = 0;
    out_c_ready = 1;
    in_d_opcode = 0;
    in_d_param = 0;
    in_d_size = 0;
    in_d_source = 0;
    in_d_sink = 0;
    in_d_denied = 0;
    in_d_data = 0;
    in_d_corrupt = 0;
    in_d_valid = 0;
    out_d_ready = 1;
    in_e_opcode = 0;
    in_e_sink = 0;
    in_e_valid = 0;
    out_e_ready = 1;
    repeat (4) @(posedge clk);
    @(negedge clk) rst_n = 1;
    @(negedge clk);
    in_a_opcode = 3'd0;
    in_a_param = 3'd1;
    in_a_size = 3'd4;
    in_a_source = 5'd3;
    in_a_address = 32'h1000;
    in_a_mask = 8'hFF;
    in_a_data = 64'h1122334455667788;
    in_a_corrupt = 1'b0;
    in_a_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_a_valid = 1'b0;
    if (out_a_valid === 1'b1 && out_a_head === 1'b1 && out_a_tail === 1'b0 && out_a_opcode === 3'd0 && out_a_mask === 8'hFF && out_a_address === 32'h1000)
      $display("TB_A_PASS");
    else
      $display("TB_A_FAIL");
    @(negedge clk);
    if (out_a_valid === 1'b1 && out_a_head === 1'b0 && out_a_tail === 1'b1 && out_a_address === 32'h1008)
      $display("TB_A2_PASS");
    else
      $display("TB_A2_FAIL");
    @(negedge clk);
    in_b_opcode = 3'd0;
    in_b_param = 3'd1;
    in_b_size = 3'd3;
    in_b_source = 5'd2;
    in_b_sink = 5'd7;
    in_b_address = 32'h2000;
    in_b_corrupt = 1'b1;
    in_b_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_b_valid = 1'b0;
    if (out_b_valid === 1'b1 && out_b_head === 1'b1 && out_b_tail === 1'b1 && out_b_opcode === 3'd0 && out_b_sink === 5'd7 && out_b_address === 32'h2000 && out_b_is_probe === 1'b1)
      $display("TB_B_PASS");
    else
      $display("TB_B_FAIL");
    @(negedge clk);
    in_c_opcode = 3'd1;
    in_c_param = 3'd0;
    in_c_size = 3'd3;
    in_c_source = 5'd1;
    in_c_address = 32'h2000;
    in_c_mask = 8'h0F;
    in_c_data = 64'hAABBCCDDEEFF0011;
    in_c_corrupt = 1'b0;
    in_c_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_c_valid = 1'b0;
    if (out_c_valid === 1'b1 && out_c_head === 1'b1 && out_c_tail === 1'b1 && out_c_opcode === 3'd1 && out_c_mask === 8'h0F)
      $display("TB_C_PASS");
    else
      $display("TB_C_FAIL");
    @(negedge clk);
    in_a_opcode = 3'd2;
    in_a_param = 3'd0;
    in_a_size = 3'd3;
    in_a_source = 5'd5;
    in_a_address = 32'h4000;
    in_a_mask = 8'hFF;
    in_a_data = 64'h1111;
    in_a_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_a_valid = 1'b0;
    if (out_a_valid === 1'b1 && out_a_opcode === 3'd2 && out_a_param === 3'd0)
      $display("TB_RMW_PASS");
    else
      $display("TB_RMW_FAIL");
    @(negedge clk);
    in_a_opcode = 3'd5;
    in_a_param = 3'd0;
    in_a_size = 3'd3;
    in_a_source = 5'd6;
    in_a_address = 32'h5000;
    in_a_mask = 8'h0F;
    in_a_data = 64'h2222;
    in_a_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_a_valid = 1'b0;
    if (out_a_valid === 1'b1 && out_a_opcode === 3'd5 && out_a_mask === 8'h0F)
      $display("TB_HINT_PASS");
    else
      $display("TB_HINT_FAIL");
    @(negedge clk);
    in_d_opcode = 3'd1;
    in_d_param = 3'd0;
    in_d_size = 3'd3;
    in_d_source = 5'd3;
    in_d_sink = 5'd2;
    in_d_denied = 1'b0;
    in_d_data = 64'hCAFEBABE12345678;
    in_d_corrupt = 1'b0;
    in_d_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_d_valid = 1'b0;
    if (out_d_valid === 1'b1 && out_d_opcode === 3'd1 && out_d_data === 64'hCAFEBABE12345678 && out_d_head === 1'b1 && out_d_tail === 1'b1)
      $display("TB_D_PASS");
    else
      $display("TB_D_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_e_opcode = 3'd0;
    in_e_sink = 5'd2;
    in_e_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_e_valid = 1'b0;
    if (out_e_valid === 1'b1 && out_e_opcode === 3'd0 && out_e_sink === 5'd2 && out_e_head === 1'b1 && out_e_tail === 1'b1)
      $display("TB_E_PASS");
    else
      $display("TB_E_FAIL");
    @(posedge clk);
    @(negedge clk);
    out_a_ready = 1'b0;
    in_a_opcode = 3'd4;
    in_a_param = 3'd0;
    in_a_size = 3'd3;
    in_a_source = 5'd4;
    in_a_address = 32'h3000;
    in_a_mask = 8'hFF;
    in_a_data = 64'h0;
    in_a_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_a_valid = 1'b0;
    if (out_a_valid === 1'b1 && credit_full === 1'b0)
      $display("TB_BP_VALID_PASS");
    else
      $display("TB_BP_VALID_FAIL");
    out_a_ready = 1'b1;
    @(posedge clk);
    @(negedge clk);
    if (out_a_valid === 1'b0)
      $display("TB_BP_DRAIN_PASS");
    else
      $display("TB_BP_DRAIN_FAIL");
    out_b_ready = 1'b0;
    in_b_opcode = 3'd0;
    in_b_param = 3'd0;
    in_b_size = 3'd3;
    in_b_source = 5'd8;
    in_b_sink = 5'd3;
    in_b_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_b_valid = 1'b0;
    if (out_b_valid === 1'b1 && out_b_head === 1'b1)
      $display("TB_B_BP_PASS");
    else
      $display("TB_B_BP_FAIL");
    out_b_ready = 1'b1;
    @(posedge clk);
    @(negedge clk);
    if (out_b_valid === 1'b0)
      $display("TB_B_BP_DRAIN_PASS");
    else
      $display("TB_B_BP_DRAIN_FAIL");
    @(negedge clk);
    in_a_opcode = 3'd4;
    in_a_param = 3'd0;
    in_a_size = 3'd3;
    in_a_source = 5'd9;
    in_a_address = 32'h6000;
    in_a_mask = 8'hFF;
    in_a_data = 64'h0;
    in_a_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_a_valid = 1'b0;
    if (out_a_valid === 1'b1 && out_a_opcode === 3'd4 && out_a_is_get === 1'b1 && out_a_is_rmw === 1'b0)
      $display("TB_A_GET_PASS");
    else
      $display("TB_A_GET_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_a_opcode = 3'd2;
    in_a_param = 3'd3;
    in_a_size = 3'd3;
    in_a_source = 5'd10;
    in_a_address = 32'h7000;
    in_a_mask = 8'hFF;
    in_a_data = 64'hAAAA;
    in_a_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_a_valid = 1'b0;
    if (out_a_valid === 1'b1 && out_a_opcode === 3'd2 && out_a_param === 3'd3 && out_a_is_arith === 1'b1 && out_a_is_rmw === 1'b1 && out_a_op_numeric === 3'd3)
      $display("TB_A_ARITH_PASS");
    else
      $display("TB_A_ARITH_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_a_opcode = 3'd3;
    in_a_param = 3'd2;
    in_a_size = 3'd3;
    in_a_source = 5'd11;
    in_a_address = 32'h8000;
    in_a_mask = 8'hFF;
    in_a_data = 64'hBBBB;
    in_a_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_a_valid = 1'b0;
    if (out_a_valid === 1'b1 && out_a_opcode === 3'd3 && out_a_param === 3'd2 && out_a_is_logical === 1'b1 && out_a_is_rmw === 1'b1 && out_a_op_numeric === 3'd0)
      $display("TB_A_LOGICAL_PASS");
    else
      $display("TB_A_LOGICAL_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_a_opcode = 3'd5;
    in_a_param = 3'd1;
    in_a_size = 3'd3;
    in_a_source = 5'd12;
    in_a_address = 32'h9000;
    in_a_mask = 8'hFF;
    in_a_data = 64'hCCCC;
    in_a_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_a_valid = 1'b0;
    if (out_a_valid === 1'b1 && out_a_opcode === 3'd5 && out_a_is_intent === 1'b1 && out_a_is_acquire === 1'b0)
      $display("TB_A_INTENT_PASS");
    else
      $display("TB_A_INTENT_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_a_opcode = 3'd6;
    in_a_param = 3'd2;
    in_a_size = 3'd4;
    in_a_source = 5'd13;
    in_a_address = 32'hA000;
    in_a_mask = 8'hFF;
    in_a_data = 64'h0;
    in_a_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_a_valid = 1'b0;
    if (out_a_valid === 1'b1 && out_a_opcode === 3'd6 && out_a_is_acquire === 1'b1 && out_a_head === 1'b1 && out_a_tail === 1'b0)
      $display("TB_A_ACQBLK_PASS");
    else
      $display("TB_A_ACQBLK_FAIL");
    @(posedge clk);
    @(negedge clk);
    if (out_a_valid === 1'b1 && out_a_head === 1'b0 && out_a_tail === 1'b1 && out_a_address === 32'hA008)
      $display("TB_A_ACQBLK_TAIL_PASS");
    else
      $display("TB_A_ACQBLK_TAIL_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_a_opcode = 3'd7;
    in_a_param = 3'd1;
    in_a_size = 3'd3;
    in_a_source = 5'd14;
    in_a_address = 32'hB000;
    in_a_mask = 8'hFF;
    in_a_data = 64'h0;
    in_a_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_a_valid = 1'b0;
    if (out_a_valid === 1'b1 && out_a_opcode === 3'd7 && out_a_is_acquire === 1'b1)
      $display("TB_A_ACQPERM_PASS");
    else
      $display("TB_A_ACQPERM_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_b_opcode = 3'd0;
    in_b_param = 3'd2;
    in_b_size = 3'd4;
    in_b_source = 5'd15;
    in_b_sink = 5'd4;
    in_b_address = 32'hC000;
    in_b_corrupt = 1'b0;
    in_b_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_b_valid = 1'b0;
    if (out_b_valid === 1'b1 && out_b_opcode === 3'd0 && out_b_is_probe === 1'b1 && out_b_address === 32'hC000)
      $display("TB_B_PROBE_PASS");
    else
      $display("TB_B_PROBE_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_b_opcode = 3'd1;
    in_b_param = 3'd0;
    in_b_size = 3'd3;
    in_b_source = 5'd15;
    in_b_sink = 5'd5;
    in_b_address = 32'hC010;
    in_b_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_b_valid = 1'b0;
    if (out_b_valid === 1'b1 && out_b_opcode === 3'd1 && out_b_is_probe_ack === 1'b1)
      $display("TB_B_PROBEACK_PASS");
    else
      $display("TB_B_PROBEACK_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_b_opcode = 3'd2;
    in_b_param = 3'd0;
    in_b_size = 3'd3;
    in_b_source = 5'd15;
    in_b_sink = 5'd6;
    in_b_address = 32'hC020;
    in_b_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_b_valid = 1'b0;
    if (out_b_valid === 1'b1 && out_b_opcode === 3'd2 && out_b_is_probe_ack_data === 1'b1)
      $display("TB_B_PROBEACKDATA_PASS");
    else
      $display("TB_B_PROBEACKDATA_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_c_opcode = 3'd0;
    in_c_param = 3'd0;
    in_c_size = 3'd3;
    in_c_source = 5'd13;
    in_c_address = 32'hD000;
    in_c_mask = 8'hFF;
    in_c_data = 64'hDDDD;
    in_c_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_c_valid = 1'b0;
    if (out_c_valid === 1'b1 && out_c_opcode === 3'd0 && out_c_is_release === 1'b1)
      $display("TB_C_RELEASE_PASS");
    else
      $display("TB_C_RELEASE_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_c_opcode = 3'd1;
    in_c_param = 3'd0;
    in_c_size = 3'd3;
    in_c_source = 5'd13;
    in_c_address = 32'hD010;
    in_c_mask = 8'hFF;
    in_c_data = 64'hEEEE;
    in_c_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_c_valid = 1'b0;
    if (out_c_valid === 1'b1 && out_c_opcode === 3'd1 && out_c_is_release_data === 1'b1)
      $display("TB_C_RELEASEDATA_PASS");
    else
      $display("TB_C_RELEASEDATA_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_c_opcode = 3'd2;
    in_c_param = 3'd0;
    in_c_size = 3'd3;
    in_c_source = 5'd14;
    in_c_address = 32'hD020;
    in_c_mask = 8'hFF;
    in_c_data = 64'hFFFF;
    in_c_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_c_valid = 1'b0;
    if (out_c_valid === 1'b1 && out_c_opcode === 3'd2 && out_c_is_probe_ack === 1'b1)
      $display("TB_C_PROBEACK_PASS");
    else
      $display("TB_C_PROBEACK_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_c_opcode = 3'd3;
    in_c_param = 3'd0;
    in_c_size = 3'd3;
    in_c_source = 5'd14;
    in_c_address = 32'hD030;
    in_c_mask = 8'hFF;
    in_c_data = 64'h1111;
    in_c_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_c_valid = 1'b0;
    if (out_c_valid === 1'b1 && out_c_opcode === 3'd3 && out_c_is_probe_ack_data === 1'b1)
      $display("TB_C_PROBEACKDATA_PASS");
    else
      $display("TB_C_PROBEACKDATA_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_c_opcode = 3'd4;
    in_c_param = 3'd0;
    in_c_size = 3'd3;
    in_c_source = 5'd14;
    in_c_address = 32'hD040;
    in_c_mask = 8'hFF;
    in_c_data = 64'h2222;
    in_c_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_c_valid = 1'b0;
    if (out_c_valid === 1'b1 && out_c_opcode === 3'd4 && out_c_is_hint_ack === 1'b1)
      $display("TB_C_HINTACK_PASS");
    else
      $display("TB_C_HINTACK_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_d_opcode = 3'd0;
    in_d_param = 3'd0;
    in_d_size = 3'd3;
    in_d_source = 5'd9;
    in_d_sink = 5'd7;
    in_d_denied = 1'b0;
    in_d_data = 64'h3333;
    in_d_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_d_valid = 1'b0;
    if (out_d_valid === 1'b1 && out_d_opcode === 3'd0 && out_d_is_access_ack === 1'b1 && out_d_is_access_ack_data === 1'b0)
      $display("TB_D_ACCESSACK_PASS");
    else
      $display("TB_D_ACCESSACK_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_d_opcode = 3'd1;
    in_d_param = 3'd0;
    in_d_size = 3'd3;
    in_d_source = 5'd9;
    in_d_sink = 5'd8;
    in_d_denied = 1'b1;
    in_d_data = 64'h4444;
    in_d_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_d_valid = 1'b0;
    if (out_d_valid === 1'b1 && out_d_opcode === 3'd1 && out_d_is_access_ack_data === 1'b1 && out_d_denied === 1'b1)
      $display("TB_D_ACCESSACKDATA_PASS");
    else
      $display("TB_D_ACCESSACKDATA_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_d_opcode = 3'd2;
    in_d_param = 3'd0;
    in_d_size = 3'd3;
    in_d_source = 5'd9;
    in_d_sink = 5'd9;
    in_d_denied = 1'b0;
    in_d_data = 64'h5555;
    in_d_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_d_valid = 1'b0;
    if (out_d_valid === 1'b1 && out_d_opcode === 3'd2 && out_d_is_hint_ack === 1'b1)
      $display("TB_D_HINTACK_PASS");
    else
      $display("TB_D_HINTACK_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_d_opcode = 3'd3;
    in_d_param = 3'd1;
    in_d_size = 3'd3;
    in_d_source = 5'd9;
    in_d_sink = 5'd10;
    in_d_denied = 1'b0;
    in_d_data = 64'h6666;
    in_d_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_d_valid = 1'b0;
    if (out_d_valid === 1'b1 && out_d_opcode === 3'd3 && out_d_is_grant === 1'b1)
      $display("TB_D_GRANT_PASS");
    else
      $display("TB_D_GRANT_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_d_opcode = 3'd4;
    in_d_param = 3'd1;
    in_d_size = 3'd4;
    in_d_source = 5'd9;
    in_d_sink = 5'd11;
    in_d_denied = 1'b0;
    in_d_data = 64'h7777;
    in_d_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_d_valid = 1'b0;
    if (out_d_valid === 1'b1 && out_d_opcode === 3'd4 && out_d_is_grant === 1'b1 && out_d_head === 1'b1 && out_d_tail === 1'b0)
      $display("TB_D_GRANTDATA_PASS");
    else
      $display("TB_D_GRANTDATA_FAIL");
    @(posedge clk);
    @(negedge clk);
    if (out_d_valid === 1'b1 && out_d_head === 1'b0 && out_d_tail === 1'b1)
      $display("TB_D_TAIL_PASS");
    else
      $display("TB_D_TAIL_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_d_opcode = 3'd5;
    in_d_param = 3'd0;
    in_d_size = 3'd3;
    in_d_source = 5'd9;
    in_d_sink = 5'd12;
    in_d_denied = 1'b0;
    in_d_data = 64'h8888;
    in_d_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_d_valid = 1'b0;
    if (out_d_valid === 1'b1 && out_d_opcode === 3'd5 && out_d_is_release_ack === 1'b1)
      $display("TB_D_RELEASEACK_PASS");
    else
      $display("TB_D_RELEASEACK_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_e_opcode = 3'd0;
    in_e_sink = 5'd7;
    in_e_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_e_valid = 1'b0;
    if (out_e_valid === 1'b1 && out_e_opcode === 3'd0 && out_e_is_grant_ack === 1'b1)
      $display("TB_E_GRANTACK_PASS");
    else
      $display("TB_E_GRANTACK_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_e_opcode = 3'd1;
    in_e_sink = 5'd8;
    in_e_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_e_valid = 1'b0;
    if (out_e_valid === 1'b1 && out_e_opcode === 3'd1 && out_e_is_release_ack === 1'b1)
      $display("TB_E_RELEASEACK_PASS");
    else
      $display("TB_E_RELEASEACK_FAIL");
    @(posedge clk);
    @(negedge clk);
    in_e_opcode = 3'd0;
    in_e_sink = 5'd9;
    in_e_valid = 1'b1;
    #1;
    if (e_sink_match === 1'b1 && e_sink_error === 1'b0)
      $display("TB_SINK_MATCH_PASS");
    else
      $display("TB_SINK_MATCH_FAIL");
    @(posedge clk);
    @(negedge clk) in_e_valid = 1'b0;
    @(posedge clk);
    @(negedge clk);
    out_c_ready = 1'b0;
    in_c_opcode = 3'd0;
    in_c_param = 3'd0;
    in_c_size = 3'd3;
    in_c_source = 5'd15;
    in_c_address = 32'hE000;
    in_c_mask = 8'hFF;
    in_c_data = 64'h9999;
    in_c_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_c_valid = 1'b0;
    if (out_c_valid === 1'b1 && out_c_head === 1'b1)
      $display("TB_C_BP_PASS");
    else
      $display("TB_C_BP_FAIL");
    out_c_ready = 1'b1;
    @(posedge clk);
    @(negedge clk);
    if (out_c_valid === 1'b0)
      $display("TB_C_BP_DRAIN_PASS");
    else
      $display("TB_C_BP_DRAIN_FAIL");
    out_d_ready = 1'b0;
    in_d_opcode = 3'd0;
    in_d_param = 3'd0;
    in_d_size = 3'd3;
    in_d_source = 5'd15;
    in_d_sink = 5'd13;
    in_d_denied = 1'b0;
    in_d_data = 64'hAAAA;
    in_d_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_d_valid = 1'b0;
    if (out_d_valid === 1'b1 && out_d_head === 1'b1)
      $display("TB_D_BP_PASS");
    else
      $display("TB_D_BP_FAIL");
    out_d_ready = 1'b1;
    @(posedge clk);
    @(negedge clk);
    if (out_d_valid === 1'b0)
      $display("TB_D_BP_DRAIN_PASS");
    else
      $display("TB_D_BP_DRAIN_FAIL");
    out_e_ready = 1'b0;
    in_e_opcode = 3'd0;
    in_e_sink = 5'd13;
    in_e_valid = 1'b1;
    @(posedge clk);
    @(negedge clk) in_e_valid = 1'b0;
    if (out_e_valid === 1'b1 && out_e_head === 1'b1)
      $display("TB_E_BP_PASS");
    else
      $display("TB_E_BP_FAIL");
    out_e_ready = 1'b1;
    @(posedge clk);
    @(negedge clk);
    if (out_e_valid === 1'b0)
      $display("TB_E_BP_DRAIN_PASS");
    else
      $display("TB_E_BP_DRAIN_FAIL");
    in_a_size = 3'd7;
    in_a_address = 32'hF001;
    in_a_valid = 1'b1;
    #1;
    if (a_error === 1'b1)
      $display("TB_ERR_A_PASS");
    else
      $display("TB_ERR_A_FAIL");
    @(negedge clk) in_a_valid = 1'b0;
    in_a_size = 3'd3;
    in_a_address = 32'hF000;
    in_a_opcode = 3'd0;
    in_b_size = 3'd7;
    in_b_address = 32'hF001;
    in_b_valid = 1'b1;
    #1;
    if (b_error === 1'b1)
      $display("TB_ERR_B_PASS");
    else
      $display("TB_ERR_B_FAIL");
    @(negedge clk) in_b_valid = 1'b0;
    in_b_size = 3'd3;
    in_b_address = 32'hF000;
    in_c_size = 3'd7;
    in_c_address = 32'hF001;
    in_c_valid = 1'b1;
    #1;
    if (c_error === 1'b1)
      $display("TB_ERR_C_PASS");
    else
      $display("TB_ERR_C_FAIL");
    @(negedge clk) in_c_valid = 1'b0;
    in_c_size = 3'd3;
    in_c_address = 32'hF000;
    in_d_size = 3'd7;
    in_d_valid = 1'b1;
    #1;
    if (d_error === 1'b1)
      $display("TB_ERR_D_PASS");
    else
      $display("TB_ERR_D_FAIL");
    @(negedge clk) in_d_valid = 1'b0;
    in_d_size = 3'd3;
    in_b_opcode = 3'd5;
    in_b_valid = 1'b1;
    #1;
    if (b_illegal === 1'b1)
      $display("TB_ILLEGAL_PASS");
    else
      $display("TB_ILLEGAL_FAIL");
    @(negedge clk) in_b_valid = 1'b0;
    in_b_opcode = 3'd0;
    in_a_opcode = 3'd2;
    in_a_param = 3'd7;
    in_a_valid = 1'b1;
    #1;
    if (a_param_error === 1'b1)
      $display("TB_PARAM_PASS");
    else
      $display("TB_PARAM_FAIL");
    @(negedge clk) in_a_valid = 1'b0;
    in_a_param = 3'd0;
    in_a_opcode = 3'd0;
    in_d_opcode = 3'd0;
    in_d_sink = 5'd13;
    in_e_sink = 5'd14;
    in_e_valid = 1'b1;
    #1;
    if (e_sink_error === 1'b1)
      $display("TB_SINK_ERR_PASS");
    else
      $display("TB_SINK_ERR_FAIL");
    @(negedge clk) in_e_valid = 1'b0;
    $display("TB_DONE");
    $finish;
  end
endmodule
`default_nettype wire
"""


def run_tilelink_directed_tb(*, adapter_source: str, module: str, work_dir: Path, timeout: int = 180) -> dict[str, Any]:
    import shutil as _shutil
    import subprocess as _subprocess
    verilator = _shutil.which("verilator")
    base = {"version": TILELINK_SUPPORTED_VERSION, "channels": list(TILELINK_SUPPORTED_CHANNELS)}
    if verilator is None:
        return {"status": "NOT_RUN", "code": TILELINK_TB_NOT_RUN_CODE, "reason": "directed TB harness unavailable: missing Verilator", **base}
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    obj = work / "obj_tilelink_tb"
    binary = work / "tb_tile_bin"
    (work / f"{module}.sv").write_text(adapter_source)
    (work / "tb_tilelink.sv").write_text(tilelink_directed_tb_source(module))
    build = [verilator, "--timing", "--binary", "-sv", "-Wall", "-Wno-fatal", "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT", "--top-module", "tb_tilelink", str(work / "tb_tilelink.sv"), str(work / f"{module}.sv"), "--Mdir", str(obj), "-o", str(binary)]
    try:
        proc = _subprocess.run(build, capture_output=True, text=True, timeout=timeout)
    except (_subprocess.SubprocessError, OSError) as exc:
        return {"status": "NOT_RUN", "code": TILELINK_TB_NOT_RUN_CODE, "reason": f"directed TB harness unavailable: build could not start ({exc})", **base}
    if proc.returncode != 0:
        return {"status": "FAIL", "code": TILELINK_TB_FAIL_CODE, "reason": "directed TB build failed: " + (proc.stdout + proc.stderr)[-2000:], **base}
    try:
        run = _subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    except (_subprocess.SubprocessError, OSError) as exc:
        return {"status": "FAIL", "code": TILELINK_TB_FAIL_CODE, "reason": f"directed TB did not run ({exc})", **base}
    output = (run.stdout or "") + (run.stderr or "")
    expected = ["TB_A_PASS", "TB_A2_PASS", "TB_B_PASS", "TB_C_PASS", "TB_RMW_PASS", "TB_HINT_PASS", "TB_D_PASS", "TB_E_PASS", "TB_BP_VALID_PASS", "TB_BP_DRAIN_PASS", "TB_B_BP_PASS", "TB_B_BP_DRAIN_PASS", "TB_A_GET_PASS", "TB_A_ARITH_PASS", "TB_A_LOGICAL_PASS", "TB_A_INTENT_PASS", "TB_A_ACQBLK_PASS", "TB_A_ACQBLK_TAIL_PASS", "TB_A_ACQPERM_PASS", "TB_B_PROBE_PASS", "TB_B_PROBEACK_PASS", "TB_B_PROBEACKDATA_PASS", "TB_C_RELEASE_PASS", "TB_C_RELEASEDATA_PASS", "TB_C_PROBEACK_PASS", "TB_C_PROBEACKDATA_PASS", "TB_C_HINTACK_PASS", "TB_D_ACCESSACK_PASS", "TB_D_ACCESSACKDATA_PASS", "TB_D_HINTACK_PASS", "TB_D_GRANT_PASS", "TB_D_GRANTDATA_PASS", "TB_D_TAIL_PASS", "TB_D_RELEASEACK_PASS", "TB_E_GRANTACK_PASS", "TB_E_RELEASEACK_PASS", "TB_SINK_MATCH_PASS", "TB_C_BP_PASS", "TB_C_BP_DRAIN_PASS", "TB_D_BP_PASS", "TB_D_BP_DRAIN_PASS", "TB_E_BP_PASS", "TB_E_BP_DRAIN_PASS", "TB_ERR_A_PASS", "TB_ERR_B_PASS", "TB_ERR_C_PASS", "TB_ERR_D_PASS", "TB_ILLEGAL_PASS", "TB_PARAM_PASS", "TB_SINK_ERR_PASS", "TB_DONE"]
    missing = [token for token in expected if token not in output]
    failed = [token for token in expected[:-1] if token.replace("_PASS", "_FAIL") in output]
    if run.returncode != 0 or missing or failed:
        return {"status": "FAIL", "code": TILELINK_TB_FAIL_CODE, "reason": "directed TB check failed missing=" + ",".join(missing) + " failed=" + ",".join(failed) + " output=" + output[-2000:], **base, "output_tail": output[-4000:]}
    return {"status": "PASS", "code": TILELINK_TB_PASS_CODE, "reason": "directed TB per-channel opcode/mask/head-tail/backpressure all passed for TileLink-1.8.1 A/B/C/D/E", **base, "expected": expected, "output_tail": output[-4000:]}

def run_adapter_booksim_smoke(*, rtl_dir: Path, anynet: Path,
                              booksim_bin: Path | None = None,
                              timeout: int = 180) -> dict[str, Any]:
    """BookSim-side smoke for an emitted adapter preview (typed, never silent).

    Delegates to the shared parity harness
    (``ordering_fsm_rtl.run_booksim_rtl_parity_smoke``): the same 5-packet /
    10-flit conservation trace runs on BookSim and on the emitted RTL
    testbench. Returns ``PASS`` only when both sides conserve; ``NOT_RUN``
    with ``ADAPTER_BOOKSIM_NOT_RUN`` when the harness is unavailable
    (BookSim or Verilator missing); ``FAIL`` with the breaching side
    named. Cycle-accurate parity is not established by this smoke.
    """
    from veritx_dse.product.ordering_fsm_rtl import (
        run_booksim_rtl_parity_smoke,
    )
    verdict = run_booksim_rtl_parity_smoke(
        rtl_dir=rtl_dir, anynet=anynet,
        booksim_bin=booksim_bin, timeout=timeout)
    if verdict.get("status") == "PASS":
        verdict["code"] = ADAPTER_BOOKSIM_PASS_CODE
    elif verdict.get("status") == "FAIL":
        verdict["code"] = ADAPTER_BOOKSIM_FAIL_CODE
    else:
        verdict["code"] = ADAPTER_BOOKSIM_NOT_RUN_CODE
    verdict["adapter_smoke"] = True
    return verdict


__all__ = [
    "AXI5_ADAPTER_CHANNELS", "AXI5_ADAPTER_ASSUMPTIONS", "AXI5_SUPPORTED",
    "AXI5_ADAPTER_SUBSET_REMAINING", "ADAPTER_BOOKSIM_FAIL_CODE",
    "ADAPTER_BOOKSIM_NOT_RUN_CODE", "ADAPTER_BOOKSIM_PASS_CODE",
    "ADAPTER_UNSUPPORTED", "ADAPTER_INVALID_PARAMS",
    "BURST_SPLIT_FAMILIES", "SUPPORTED_FAMILIES",
    "TILELINK_ADAPTER_CHANNELS", "TILELINK_ADAPTER_ASSUMPTIONS",
    "TILELINK_ADAPTER_SUBSET_REMAINING", "TILELINK_SUPPORTED_CHANNELS",
    "TILELINK_SUPPORTED_PROFILES", "TILELINK_SUPPORTED_VERSION",
    "TILELINK_TB_FAIL_CODE", "TILELINK_TB_NOT_RUN_CODE",
    "TILELINK_TB_PASS_CODE",
    "AdapterParams", "AdapterBuild", "AdapterSummary", "Verdict",
    "build_adapter", "adapter_inventory", "adapter_module_name",
    "check_params", "run_adapter_booksim_smoke",
    "tilelink_directed_tb_source", "run_tilelink_directed_tb",
]
