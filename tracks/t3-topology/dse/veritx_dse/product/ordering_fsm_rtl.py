"""ordering_fsm_rtl — M2 OrderingFSM + VC reassignment emitter.

Deep module with a narrow interface (STAGE 3 §2, LiveFabric pattern):

    build_ordering_fsm(policy: OrderingPolicy) -> OrderingEmission
        # policy struct in -> emitted module + verdict out

The caller passes one frozen policy (projected from ``agent_intents`` +
``traffic_policy``) and gets back one verdict plus at most one SV source.
No ``CompileRequestV4`` is imported (module-isolation contract, STAGE 1
§8.3): extraction from the request is a duck-typed projection
(``policy_from_request``), exactly like ``addr_decode_rtl``.

What the emitted ``ordering_fsm.sv`` realizes (STAGE 3 §3.5/§3.4):

* ``agent_intents[].ordering`` -> ``ORDERING_MODE`` localparam +
  sequence enforcement (STRONG stalls on gap, RELAXED flags beyond the
  outstanding window without stalling, RAW bypasses).
* ``agent_intents[].max_outstanding`` -> ``MAX_OUTSTANDING`` localparam +
  outstanding-credit counter with backpressure (``in_ready`` low when
  full). Absent = no cap; the module never invents a bound.
* ``agent_intents[].split_at`` -> ``SPLIT_AT`` localparam + split counter
  that aligns burst boundaries (TAIL at the split point, HEAD after).
* ``traffic_policy.traffic_class_vcs`` -> CLASS_ID enumeration + VC
  reassignment case table. VC0 routes via ``RT_MIN`` (free table), VC1
  via ``RT_ESC`` (escape table): the route tables themselves are the
  emitter's, the *selection* is the policy's.

Handshake invariant (consistent ready/valid): one forwarding permission
``fwd_permits = !outstanding_full && (MODE != strong || in_order)``
governs both sides. ``in_ready = out_ready && fwd_permits`` and
``out_valid = in_valid && fwd_permits`` share the same accept signal, so
an upstream fire (``in_valid && in_ready``) and a downstream fire
(``out_valid && out_ready``) are the same event. When blocked
(``fwd_permits = 0``: strong gap or full outstanding), ``in_ready = 0``
and ``out_valid = 0`` together: zero downstream accepts while the source
holds its beat stable; ``expected_seq``/``split_cnt``/``outstanding_cnt``
advance nowhere until the held beat is accepted. ``out_valid`` does not
depend combinationally on ``out_ready`` (``in_ready`` does, as a ready
chain). This block is fixed in isolation; it is not connected into
``noc_top`` by this emitter.

LiveFabric translation (backend-only; prototype src untouched): the
emission carries a read-only *summary* (policy echo + VC table + route
binding), an *evidence* record (hash / lint / parity) and an
*Assumptions* row set (``not_established``) — never a bare module. A
refusal is returned in place as a typed verdict, never hidden.

Backward compatibility: ``policy_from_request`` on a request with no
M2 fields yields an empty policy; ``build_ordering_fsm`` returns
``sv_source=None`` and the preview emits no file, so empty-policy output
is byte-identical to the historical 2-VC preview.

Fail closed: a policy the 2-VC preview slice cannot realize (a traffic
class on VC>=2, a shared wire, relaxed without a window, disagreeing
per-group knobs) yields ``ok=False`` with code
``UNSUPPORTED_STAGE1_REALIZATION`` naming OrderingFSM. The caller must
not emit a substitute.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: VCs the M2 preview slice implements: VC0 free (RT_MIN), VC1 escape (RT_ESC).
EMITTED_VCS = 2

#: Typed codes (mirrors catalog_evaluation's bearer).
UNSUPPORTED_CODE = "UNSUPPORTED_STAGE1_REALIZATION"
EMITTED_CODE = "ORDERING_FSM_EMITTED"
NOT_DECLARED_CODE = "NOT_DECLARED"
PARITY_UNAVAILABLE_CODE = "PARITY_HARNESS_UNAVAILABLE"
PARITY_PASS_CODE = "PARITY_PASS"
PARITY_FAIL_CODE = "PARITY_FAIL"
PARITY_NOT_RUN_CODE = "PARITY_NOT_RUN"

_ORDERING_CODE = {"raw": 0, "strong": 1, "relaxed": 2}
_ROUTE_TABLE = {0: "RT_MIN(free)", 1: "RT_ESC(escape)"}


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _bits_for_count(value: int) -> int:
    return max(1, int(value).bit_length())


@dataclass(frozen=True)
class OrderingPolicy:
    """One frozen policy struct for the OrderingFSM deep module.

    ``traffic_class_vcs`` is ``((class_name, vc), ...)`` sorted by class
    name; the sorted order defines CLASS_ID 0..N-1 (documented in the
    emitted SV header so a reviewer can re-derive the enumeration).
    """

    ordering: str | None = None
    max_outstanding: int | None = None
    split_at: int | None = None
    traffic_class_vcs: tuple[tuple[str, int], ...] = ()
    agent_indices: tuple[int, ...] = ()

    def is_empty(self) -> bool:
        return (
            self.ordering is None
            and self.max_outstanding is None
            and self.split_at is None
            and not self.traffic_class_vcs
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordering": self.ordering,
            "max_outstanding": self.max_outstanding,
            "split_at": self.split_at,
            "traffic_class_vcs": [
                {"traffic_class": name, "vc": vc}
                for name, vc in self.traffic_class_vcs
            ],
            "agent_indices": list(self.agent_indices),
        }


@dataclass(frozen=True)
class OrderingVerdict:
    ok: bool
    code: str
    reason: str | None = None
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrderingEmission:
    verdict: OrderingVerdict
    sv_source: str | None
    knob_map: tuple[tuple[str, str], ...] = ()
    not_established: tuple[str, ...] = ()


def policy_from_request(request: Any) -> OrderingPolicy:
    """Project agent intents + traffic policy into one OrderingPolicy.

    Only the agreed value survives: when two groups declare different
    orderings / maxima / splits, the projection keeps the first in
    ``agent_idx`` order and the disagreement is a fail-closed verdict in
    :func:`build_ordering_fsm` (the preview has one FSM instance, not
    one per agent group).
    """
    intents = tuple(getattr(request, "agent_intents", ()) or ())
    policy = getattr(request, "traffic_policy", None)
    desired = tuple(getattr(policy, "traffic_class_vcs", ()) or ())
    class_vcs = tuple(sorted(
        (str(getattr(row, "traffic_class", row)), int(getattr(row, "vc")))
        for row in desired
    ))
    orderings = sorted({_enum_value(getattr(i, "ordering", None)) for i in intents
                        if getattr(i, "ordering", None) is not None})
    maxima = sorted({i.max_outstanding for i in intents
                     if getattr(i, "max_outstanding", None) is not None})
    splits = sorted({i.split_at for i in intents
                     if getattr(i, "split_at", None) is not None})
    # Disagreement is carried as parallel tuples on the verdict path via
    # the sentinel: keep first values here; build validates uniqueness by
    # re-scanning the request intents. For the common cases (zero or one
    # declaring group, or uniform groups) the first value is correct.
    ordering = orderings[0] if len(orderings) == 1 else (
        orderings[0] if orderings else None)
    # When groups disagree, ordering is set but _disagreement detects it.
    max_outstanding = maxima[0] if maxima else None
    split_at = splits[0] if splits else None
    indices = tuple(sorted({int(getattr(i, "agent_idx", 0)) for i in intents}))
    # Store first-or-disagree markers: build re-derives the sets.
    # To make disagreement detectable from the policy alone, encode it
    # in agent_indices as (-1,) when groups disagree on any knob.
    if len(orderings) > 1 or len(maxima) > 1 or len(splits) > 1:
        indices = (-1,)
    return OrderingPolicy(
        ordering=ordering if len(orderings) <= 1 else orderings[0],
        max_outstanding=max_outstanding,
        split_at=split_at,
        traffic_class_vcs=class_vcs,
        agent_indices=indices,
    )


def _init_w(policy: OrderingPolicy) -> int:
    indices = policy.agent_indices
    if indices and indices != (-1,):
        return _bits_for_count(max(indices))
    return 2


def _knob_map(policy: OrderingPolicy) -> tuple[tuple[str, str], ...]:
    mode = _ORDERING_CODE[policy.ordering] if policy.ordering else 0
    return (
        ("agent_intents[].ordering", f"ordering_fsm.sv ORDERING_MODE={mode} ({policy.ordering or 'raw/bypass'})"),
        ("agent_intents[].max_outstanding", f"ordering_fsm.sv MAX_OUTSTANDING={policy.max_outstanding if policy.max_outstanding is not None else 0} (0=no cap) + outstanding counter"),
        ("agent_intents[].split_at", f"ordering_fsm.sv SPLIT_AT={policy.split_at if policy.split_at is not None else 0} (0=no split) + split counter/alignment"),
        ("traffic_policy.traffic_class_vcs[].traffic_class", "ordering_fsm.sv CLASS_ID enumeration (sorted class names) + class_in selector"),
        ("traffic_policy.traffic_class_vcs[].vc", "ordering_fsm.sv assigned_vc + flit class bits; VC0->RT_MIN(free), VC1->RT_ESC(escape)"),
    )


_NOT_ESTABLISHED = (
    "Cycle-accurate BookSim/RTL parity: smoke conservation only; exact "
    "routing decisions, timing and latency are not established.",
    "Physical timing (STA): no synthesis, placement or clock-tree claim "
    "is made for the emitted preview Verilog.",
    "Full AXI5 protocol shim: burst-split alignment only; handshake, "
    "credit-id remap and framing are not established.",
    "Per-domain ordering is banked per (initiator, class); the ordering "
    "MODE is still shared across domains (disagreeing per-group modes are "
    "refused, never merged), and more than 2^INIT_W initiators per class "
    "is refused. Out-of-order burst completion is a typed refusal "
    "(complete_mismatch).",
    "Reorder buffering: strong enforcement is stall-on-violation (no "
    "holding buffer); out-of-order delivery is flagged, not reordered.",
)


def build_ordering_fsm(policy: OrderingPolicy, *, emitted_vcs: int = EMITTED_VCS,
                       shared_wires: int = 0) -> OrderingEmission:
    """One policy struct in -> emitted module + verdict out (deep module API)."""
    if policy.is_empty():
        return OrderingEmission(
            OrderingVerdict(True, NOT_DECLARED_CODE,
                            "no M2 ordering/VC policy declared; no OrderingFSM is emitted "
                            "(the historical 2-VC preview is byte-identical)."),
            None, (), _NOT_ESTABLISHED)
    def refuse(reason: str) -> OrderingEmission:
        return OrderingEmission(
            OrderingVerdict(False, UNSUPPORTED_CODE, reason),
            None, (), _NOT_ESTABLISHED)
    if policy.agent_indices == (-1,):
        return refuse(
            f"{UNSUPPORTED_CODE}: agent groups declare disagreeing ordering / "
            f"max_outstanding / split_at values; the preview emits one "
            f"OrderingFSM instance and cannot represent per-group divergence "
            f"(owner stage = RTL generation; module = OrderingFSM).")
    if policy.ordering is not None and policy.ordering not in _ORDERING_CODE:
        return refuse(
            f"{UNSUPPORTED_CODE}: ordering {policy.ordering!r} has no "
            f"OrderingFSM mode (expected one of {sorted(_ORDERING_CODE)}) "
            f"(owner stage = RTL generation; module = OrderingFSM).")
    if policy.max_outstanding is not None and policy.max_outstanding < 1:
        return refuse(
            f"{UNSUPPORTED_CODE}: max_outstanding={policy.max_outstanding} "
            f"is not a legal bound (>=1) for the OrderingFSM outstanding "
            f"counter (owner stage = RTL generation; module = OrderingFSM).")
    if policy.split_at is not None and policy.split_at < 1:
        return refuse(
            f"{UNSUPPORTED_CODE}: split_at={policy.split_at} is not a legal "
            f"split threshold (>=1) for the OrderingFSM split alignment "
            f"(owner stage = RTL generation; module = OrderingFSM).")
    if policy.ordering == "relaxed" and policy.max_outstanding is None:
        return refuse(
            f"{UNSUPPORTED_CODE}: ordering='relaxed' needs max_outstanding "
            f"to define the reorder window; the preview will not invent a "
            f"window (declare max_outstanding or use 'strong'/'raw') "
            f"(owner stage = RTL generation; module = OrderingFSM).")
    for name, vc in policy.traffic_class_vcs:
        if not 0 <= vc < emitted_vcs:
            return refuse(
                f"{UNSUPPORTED_CODE}: traffic class {name!r} requires VC{vc} "
                f"but the preview implements {emitted_vcs} VCs (VC0 free + "
                f"VC1 escape, 64-bit flits); no >2-VC substitute is emitted "
                f"(owner stage = RTL generation; module = OrderingFSM).")
    if shared_wires:
        return refuse(
            f"{UNSUPPORTED_CODE}: the OrderingFSM policy cannot be emitted "
            f"on {shared_wires} shared (multi-drop) wire(s); the preview is "
            f"point-to-point only and shared-wire semantics are not "
            f"generalized into a substitute (owner stage = RTL generation; "
            f"module = OrderingFSM).")
    return OrderingEmission(
        OrderingVerdict(True, EMITTED_CODE,
                        "OrderingFSM slice realized within 2 VCs (VC0/RT_MIN, "
                        "VC1/RT_ESC); route selection follows traffic_policy."),
        render_ordering_fsm(policy),
        _knob_map(policy),
        _NOT_ESTABLISHED,
    )


def render_ordering_fsm(policy: OrderingPolicy) -> str:
    mode = _ORDERING_CODE.get(policy.ordering or "raw", 0)
    max_out = policy.max_outstanding if policy.max_outstanding is not None else 0
    split_at = policy.split_at if policy.split_at is not None else 0
    init_w = _init_w(policy)
    burst_depth = max_out if max_out else 64
    classes = policy.traffic_class_vcs
    names = [name for name, _vc in classes] or ["__default__"]
    num_classes = len(names)
    class_w = max(1, (num_classes - 1).bit_length())
    vc_by_id = {i: (classes[i][1] if i < len(classes) else 0)
                for i in range(num_classes)}
    lines = [
        "`default_nettype none",
        "",
        "module ordering_fsm #(",
        f"  parameter int ORDERING_MODE = {mode},",
        f"  parameter int MAX_OUTSTANDING = {max_out},",
        f"  parameter int SPLIT_AT = {split_at},",
        f"  parameter int CLASS_W = {class_w},",
        f"  parameter int INIT_W = {init_w},",
        f"  parameter int BURST_DEPTH = {burst_depth},",
        "  parameter int VC_W = 1",
        ") (",
        "  input  logic clk,",
        "  input  logic rst_n,",
        "  input  logic in_valid,",
        "  output logic in_ready,",
        "  input  logic [63:0] in_flit,",
        "  input  logic [INIT_W-1:0] initiator_in,",
        "  input  logic [CLASS_W-1:0] class_in,",
        "  input  logic complete_pulse,",
        "  input  logic complete_tagged,",
        "  input  logic [12:0] complete_seq,",
        "  input  logic [INIT_W-1:0] complete_initiator,",
        "  input  logic [CLASS_W-1:0] complete_class,",
        "  output logic out_valid,",
        "  input  logic out_ready,",
        "  output logic [63:0] out_flit,",
        "  output logic [VC_W-1:0] assigned_vc,",
        "  output logic order_violation,",
        "  output logic outstanding_full,",
        "  output logic split_required,",
        "  output logic complete_mismatch,",
        "  output logic burst_journal_overflow",
        ");",
        "",
        "  localparam int DOMAIN_W = INIT_W + CLASS_W;",
        "  localparam int N_DOMAINS = 1 << DOMAIN_W;",
        "  localparam int BURST_IDX_W = (BURST_DEPTH > 1)",
        "      ? $clog2(BURST_DEPTH) : 1;",
        "  logic [DOMAIN_W-1:0] dom_sel;",
        "  logic [DOMAIN_W-1:0] cmp_dom_sel;",
        "  logic [12:0] seq_in;",
        "  logic [12:0] fwd_gap;",
        "  int seq_gap;",
        "  logic [12:0] expected_seq_arr [N_DOMAINS];",
        "  logic [12:0] expected_seq_sel;",
        "  logic signed [31:0] outstanding_arr [N_DOMAINS];",
        "  logic signed [31:0] split_cnt_arr [N_DOMAINS];",
        "  logic split_pending_arr [N_DOMAINS];",
        "  logic [12:0] burst_head_seq_arr [N_DOMAINS];",
        "  logic signed [31:0] burst_open_cnt_arr [N_DOMAINS];",
        "  logic [12:0] burst_journal_head_seq [BURST_DEPTH];",
        "  logic [DOMAIN_W-1:0] burst_journal_domain [BURST_DEPTH];",
        "  logic signed [31:0] burst_journal_remaining [BURST_DEPTH];",
        "  logic [BURST_IDX_W-1:0] burst_head_idx;",
        "  logic [BURST_IDX_W-1:0] burst_tail_idx;",
        "  int burst_count;",
        "  logic in_order;",
        "  logic within_window;",
        "  logic full_sel;",
        "  logic fwd_permits;",
        "  logic accept;",
        "  logic [VC_W-1:0] vc_of_class;",
        "  logic [1:0] flit_type;",
        "  logic burst_close;",
        "  int burst_close_beats;",
        "  logic [12:0] close_head_seq;",
        "  logic push_ok;",
        "  logic journal_head_valid;",
        "  logic journal_head_match;",
        "  logic tagged_retire;",
        "  logic legacy_retire;",
        "  logic [DOMAIN_W-1:0] retire_dom;",
        "  int retire_beats;",
        "  int burst_count_next;",
        "  wire in_flit_vc_dropped = in_flit[63];",
        "",
        "  always_comb begin",
        "    vc_of_class = 1'b0;",
        "    case (class_in)",
    ]
    for i in range(num_classes):
        lines.append(
            f"      {i}: vc_of_class = 1'b{vc_by_id[i]};")
    lines.extend([
        "      default: vc_of_class = 1'b0;",
        "    endcase",
        "  end",
        "",
        "  assign assigned_vc = vc_of_class;",
        "  assign out_flit[63] = vc_of_class;",
        "  assign out_flit[62:61] = flit_type;",
        "  assign out_flit[60:0] = in_flit[60:0];",
        "  assign seq_in = in_flit[44:32];",
        "  assign dom_sel = {initiator_in, class_in};",
        "  assign cmp_dom_sel = {complete_initiator, complete_class};",
        "  assign expected_seq_sel = expected_seq_arr[dom_sel];",
        "  assign fwd_gap = seq_in - expected_seq_sel;",
        "  assign seq_gap = int'(fwd_gap);",
        "  assign in_order = (seq_gap == 0);",
        "  assign within_window = (seq_gap <= MAX_OUTSTANDING);",
        "  assign order_violation = (ORDERING_MODE == 1) ? (in_valid && !in_order)",
        "                           : ((ORDERING_MODE == 2) ? (in_valid && !within_window && !in_order) : 1'b0);",
        "  assign full_sel = (MAX_OUTSTANDING == 0) ? 1'b0",
        "                    : (outstanding_arr[dom_sel] >= MAX_OUTSTANDING);",
        "  assign outstanding_full = full_sel;",
        "  assign fwd_permits = !full_sel",
        "                     && ((ORDERING_MODE != 1) || in_order);",
        "  assign in_ready = out_ready && fwd_permits;",
        "  assign out_valid = in_valid && fwd_permits;",
        "  assign accept = in_valid && in_ready;",
        "  assign burst_close = accept",
        "      && ((SPLIT_AT == 0) || (split_cnt_arr[dom_sel] == (SPLIT_AT - 1)));",
        "  assign burst_close_beats = (SPLIT_AT == 0) ? 1",
        "      : (burst_open_cnt_arr[dom_sel] + 1);",
        "  assign close_head_seq = (burst_open_cnt_arr[dom_sel] == 0) ? seq_in",
        "      : burst_head_seq_arr[dom_sel];",
        "  assign push_ok = burst_close && (burst_count < BURST_DEPTH);",
        "  assign burst_journal_overflow = burst_close",
        "      && (burst_count >= BURST_DEPTH);",
        "  assign journal_head_valid = (burst_count > 0);",
        "  assign journal_head_match = journal_head_valid",
        "      && (burst_journal_head_seq[burst_head_idx] == complete_seq)",
        "      && (burst_journal_domain[burst_head_idx] == cmp_dom_sel);",
        "  assign tagged_retire = complete_pulse && complete_tagged",
        "      && journal_head_match;",
        "  assign legacy_retire = complete_pulse && !complete_tagged",
        "      && journal_head_valid;",
        "  assign complete_mismatch = complete_pulse && complete_tagged",
        "      && !journal_head_match",
        "      || (in_flit_vc_dropped && 1'b0);",
        "  assign retire_dom = journal_head_valid",
        "      ? burst_journal_domain[burst_head_idx] : cmp_dom_sel;",
        "  assign retire_beats = tagged_retire",
        "      ? burst_journal_remaining[burst_head_idx] : 1;",
        "  assign split_required = (SPLIT_AT != 0)",
        "      && (split_cnt_arr[dom_sel] == (SPLIT_AT - 1));",
        "  assign flit_type = (SPLIT_AT == 0) ? in_flit[62:61]",
        "                   : (split_required ? 2'd2",
        "                   : (split_pending_arr[dom_sel] ? 2'd0 : in_flit[62:61]));",
        "  always_comb begin",
        "    burst_count_next = burst_count",
        "        + (push_ok ? 1 : 0);",
        "    if (tagged_retire)",
        "      burst_count_next = burst_count_next - 1;",
        "    else if (legacy_retire",
        "             && (burst_journal_remaining[burst_head_idx] <= 1))",
        "      burst_count_next = burst_count_next - 1;",
        "  end",
        "",
        "  always_ff @(posedge clk or negedge rst_n) begin",
        "    if (!rst_n) begin",
        "      for (int i = 0; i < N_DOMAINS; i++) begin",
        "        expected_seq_arr[i] <= 13'd0;",
        "        outstanding_arr[i] <= 0;",
        "        split_cnt_arr[i] <= 0;",
        "        split_pending_arr[i] <= 1'b0;",
        "        burst_head_seq_arr[i] <= 13'd0;",
        "        burst_open_cnt_arr[i] <= 0;",
        "      end",
        "      for (int j = 0; j < BURST_DEPTH; j++) begin",
        "        burst_journal_head_seq[j] <= 13'd0;",
        "        burst_journal_domain[j] <= '0;",
        "        burst_journal_remaining[j] <= 0;",
        "      end",
        "      burst_head_idx <= '0;",
        "      burst_tail_idx <= '0;",
        "      burst_count <= 0;",
        "    end else begin",
        "      if (accept) begin",
        "        expected_seq_arr[dom_sel] <= seq_in + 13'd1;",
        "        if (SPLIT_AT != 0 && split_cnt_arr[dom_sel] == (SPLIT_AT - 1)) begin",
        "          split_cnt_arr[dom_sel] <= 0;",
        "          split_pending_arr[dom_sel] <= 1'b1;",
        "        end else if (SPLIT_AT != 0) begin",
        "          split_cnt_arr[dom_sel] <= split_cnt_arr[dom_sel] + 1;",
        "          split_pending_arr[dom_sel] <= 1'b0;",
        "        end",
        "        if (split_pending_arr[dom_sel]",
        "            || (burst_open_cnt_arr[dom_sel] == 0)) begin",
        "          burst_head_seq_arr[dom_sel] <= seq_in;",
        "          burst_open_cnt_arr[dom_sel] <= 1;",
        "        end else begin",
        "          burst_open_cnt_arr[dom_sel] <= burst_open_cnt_arr[dom_sel] + 1;",
        "        end",
        "        if (burst_close) begin",
        "          burst_open_cnt_arr[dom_sel] <= 0;",
        "          burst_head_seq_arr[dom_sel] <= seq_in;",
        "        end",
        "      end",
        "      for (int i = 0; i < N_DOMAINS; i++) begin",
        "        if (i == int'(dom_sel) && i == int'(retire_dom)) begin",
        "          if (accept && (complete_pulse && (tagged_retire || legacy_retire)))",
        "            outstanding_arr[i] <= outstanding_arr[i] + 1 - retire_beats;",
        "          else if (complete_pulse && complete_tagged && !tagged_retire)",
        "            outstanding_arr[i] <= outstanding_arr[i] + (accept ? 1 : 0);",
        "          else if (accept)",
        "            outstanding_arr[i] <= outstanding_arr[i] + 1;",
        "          else if (complete_pulse && (tagged_retire || legacy_retire))",
        "            outstanding_arr[i] <= outstanding_arr[i] - retire_beats;",
        "          else if (complete_pulse && !complete_tagged",
        "                   && !journal_head_valid && (outstanding_arr[i] > 0))",
        "            outstanding_arr[i] <= outstanding_arr[i] - 1;",
        "        end else if (i == int'(dom_sel) && accept) begin",
        "          outstanding_arr[i] <= outstanding_arr[i] + 1;",
        "        end else if (i == int'(retire_dom)",
        "                   && complete_pulse && (tagged_retire || legacy_retire)) begin",
        "          outstanding_arr[i] <= outstanding_arr[i] - retire_beats;",
        "        end else if (i == int'(retire_dom)",
        "                   && complete_pulse && !complete_tagged",
        "                   && !journal_head_valid && (outstanding_arr[i] > 0)) begin",
        "          outstanding_arr[i] <= outstanding_arr[i] - 1;",
        "        end",
        "      end",
        "      if (push_ok) begin",
        "        burst_journal_head_seq[burst_tail_idx] <= close_head_seq;",
        "        burst_journal_domain[burst_tail_idx] <= dom_sel;",
        "        burst_journal_remaining[burst_tail_idx] <= burst_close_beats;",
        "        burst_tail_idx <= (burst_tail_idx == BURST_IDX_W'(BURST_DEPTH - 1))",
        "          ? BURST_IDX_W'(0) : BURST_IDX_W'(burst_tail_idx + 1);",
        "      end",
        "      if (tagged_retire) begin",
        "        burst_head_idx <= (burst_head_idx == BURST_IDX_W'(BURST_DEPTH - 1))",
        "          ? BURST_IDX_W'(0) : BURST_IDX_W'(burst_head_idx + 1);",
        "      end else if (legacy_retire) begin",
        "        if (burst_journal_remaining[burst_head_idx] <= 1) begin",
        "          burst_head_idx <= (burst_head_idx == BURST_IDX_W'(BURST_DEPTH - 1))",
        "            ? BURST_IDX_W'(0) : BURST_IDX_W'(burst_head_idx + 1);",
        "        end else begin",
        "          burst_journal_remaining[burst_head_idx] <= burst_journal_remaining[burst_head_idx] - 1;",
        "        end",
        "      end",
        "      burst_count <= burst_count_next;",
        "    end",
        "  end",
        "",
        "endmodule",
        "`default_nettype wire",
        "",
    ])
    return "\n".join(lines)


#: Cycle-accurate parity comparisons (BookSim completion cycles vs the
#: Verilator TB's last-ejection cycle, per-flit ejection log, payload set).
#: These are measurements recorded as observed numbers with deltas — the
#: two microarchitectures are NOT cycle-equal and equality is never forced.

_EJECTION_RE = None  # compiled lazily in _parse_ejection_log

#: SMOKE_TRACE is the single 5-packet trace both simulators consume.
SMOKE_TRACE_TEXT = "0 0 0 3 2\n0 1 1 2 2\n1 2 0 0 2\n1 3 1 1 2\n2 0 0 3 2\n"


def _router_count_from_anynet(anynet: Path) -> int | None:
    """Router count from an anynet file (one ``router <id>`` line per router)."""
    try:
        text = Path(anynet).read_text()
    except OSError:
        return None
    count = 0
    for line in text.splitlines():
        if line.startswith("router ") or line.startswith("node "):
            # anynet lines look like "router 0 node 0 router 1 ..."; count
            # only the leading "router <id>" declaration per line.
            if line.startswith("router "):
                count += 1
    return count or None


def _expected_packets_from_trace(trace_text: str,
                                 n_routers: int | None) -> list[dict[str, Any]]:
    """Packets the trace declares, after the TB's id mapping (``mod N``).

    Trace lines are ``cyc src cl dst sz``; the Verilator TB maps
    ``src % N`` / ``dst % N`` and keeps ``sz`` flits per packet with
    escape = ``cl & 1``. BookSim consumes the matrix unmapped (node ids
    must already be in range for the smoke trace).
    """
    # pylint: disable=unused-argument
    packets: list[dict[str, Any]] = []
    for index, line in enumerate(trace_text.splitlines()):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 5:
            continue
        cyc, src, cls, dst, size = (int(x) for x in fields)
        packets.append({
            "index": index,
            "cyc": cyc,
            "src": src % n_routers if n_routers else src,
            "dst": dst % n_routers if n_routers else dst,
            "cls": cls,
            "esc": cls & 1,
            "flits": size,
        })
    return packets


def _parse_ejection_log(stdout: str) -> list[dict[str, Any]]:
    """Per-flit ejection records the TB prints (cycle-granular deliveries).

    TB lines look like ``EJ cyc=5 r=0 src=2 dst=0 seq=1 typ=0``. The TB
    prints only the first 30 ejections, so a log shorter than the CL_JSON
    ejected count means the log was truncated (payload comparison is then
    incomplete and flagged, never silently exact).
    """
    import re
    rows: list[dict[str, Any]] = []
    pattern = re.compile(
        r"EJ cyc=(\d+) r=(\d+) src=(\d+) dst=(\d+) seq=(\d+) typ=(\d+)")
    for cyc, router, src, dst, seq, typ in pattern.findall(stdout):
        rows.append({"cyc": int(cyc), "router": int(router),
                     "src": int(src), "dst": int(dst), "seq": int(seq),
                     "typ": int(typ)})
    return rows


def _parse_results_counts(stdout: str) -> dict[str, Any]:
    """free/esc packet counts + wrong-destination count from ``=== RESULTS ===``."""
    import re
    counts: dict[str, Any] = {"free_packets": None, "esc_packets": None,
                              "wrong_dst": None}
    match = re.search(r"injected:\s+\d+ \(free=(\d+), esc=(\d+)\)", stdout)
    if match is not None:
        counts["free_packets"] = int(match.group(1))
        counts["esc_packets"] = int(match.group(2))
    match = re.search(r"wrong_dst:\s+(\d+)", stdout)
    if match is not None:
        counts["wrong_dst"] = int(match.group(1))
    return counts


def _compare_delivered_payloads(
        packets: list[dict[str, Any]],
        ejection_log: list[dict[str, Any]],
        rtl_ejected: int | None) -> dict[str, Any]:
    """Delivered payload comparison: trace-expected set vs RTL ejections.

    Counts flits per ``(src, dst)`` and HEAD/TAIL/BODY type totals; the
    BookSim side emits no per-flit delivery log, so its corroboration is
    by delivered/flit totals only (stated in the scope note).
    """
    expected: dict[tuple[int, int], int] = {}
    for packet in packets:
        key = (packet["src"], packet["dst"])
        expected[key] = expected.get(key, 0) + packet["flits"]
    observed: dict[tuple[int, int], int] = {}
    for row in ejection_log:
        key = (row["src"], row["dst"])
        observed[key] = observed.get(key, 0) + 1
    expected_types = {0: len(packets), 2: len(packets),
                      1: sum(max(0, p["flits"] - 2) for p in packets),
                      3: sum(1 for p in packets if p["flits"] == 1)}
    observed_types = {typ: sum(1 for row in ejection_log if row["typ"] == typ)
                      for typ in (0, 1, 2, 3)}
    complete = (rtl_ejected is not None and len(ejection_log) >= rtl_ejected)
    if not complete:
        return {"match": None,
                "scope": "incomplete: ejection log truncated by the TB "
                         "(first 30 ejections only); payload comparison is "
                         "not exact",
                "expected_by_pair": {f"{a}->{b}": n
                                      for (a, b), n in sorted(expected.items())},
                "observed_by_pair": {f"{a}->{b}": n
                                      for (a, b), n in sorted(observed.items())},
                "expected_types": expected_types,
                "observed_types": observed_types}
    match = (expected == observed and expected_types == observed_types)
    return {"match": match,
            "scope": "exact set comparison of RTL ejections against the "
                     "trace-declared (src, dst, flit-type) multiset; "
                     "BookSim emits no per-flit delivery log, so its "
                     "delivered-payload corroboration is by delivered/flit "
                     "totals only, not per-flit",
            "expected_by_pair": {f"{a}->{b}": n
                                 for (a, b), n in sorted(expected.items())},
            "observed_by_pair": {f"{a}->{b}": n
                                 for (a, b), n in sorted(observed.items())},
            "expected_types": expected_types,
            "observed_types": observed_types}


def _parse_calibration_json(stdout: str) -> dict[str, Any] | None:
    for line in stdout.splitlines():
        if "CAL_JSON:" in line:
            payload = line.split("CAL_JSON:", 1)[1].strip()
            try:
                import json
                return json.loads(payload)
            except (ValueError, TypeError):
                return None
    return None


def run_booksim_rtl_parity_smoke(*, rtl_dir: Path, anynet: Path,
                                  booksim_bin: Path | None = None,
                                  timeout: int = 180) -> dict[str, Any]:
    """Cycle-accurate BookSim vs RTL parity smoke (typed, never skipped).

    Runs the same short ``trace`` (5 packets / 10 flits, classes 0+1) on
    BookSim (throughput, ``num_vcs=2``) and on the emitted RTL's
    Verilator testbench (``NOC_TRACE_FILE``) and returns a typed verdict:

    * ``status=PASS, code=PARITY_PASS`` only when both sides conserve
      (delivered==completed==5, flits injected==accepted==ejected==10),
      the RTL delivered-payload set matches the trace exactly, and the
      per-class flit counts agree.
    * ``status=NOT_RUN, code=PARITY_HARNESS_UNAVAILABLE`` when a binary
      the harness needs is missing (verilator or BookSim) — the caller
      must surface this row, never pytest.skip it silently.
    * ``status=FAIL`` with the breaching side named.

    Cycle-accurate mode: the manifest additionally compares delivered
    payloads (RTL per-flit ejection log vs the trace), flit counts
    (overall and per class), drain cycles (BookSim ``completion_cycles``
    vs the RTL last-ejection cycle) and latency populations. Observed
    cycle deltas are recorded as numbers (``cycle_accurate`` block) and
    are NOT forced equal — the two microarchitectures differ, so
    ``cycle_exact`` is reported honestly (expected False) and is not a
    PASS condition; PASS means payload/count parity, not cycle equality.
    """
    import shutil
    repo = Path(__file__).resolve().parents[5]
    candidates = [
        repo / "third_party" / "booksim2" / "src" / "booksim",
    ]
    binary = booksim_bin
    if binary is None:
        binary = next((p for p in candidates if p.is_file()), None)
    verilator = shutil.which("verilator")
    missing = []
    if binary is None or not Path(binary).is_file():
        missing.append("BookSim binary (third_party/booksim2/src/booksim)")
    if verilator is None:
        missing.append("Verilator")
    if missing:
        return {"status": "NOT_RUN", "code": PARITY_UNAVAILABLE_CODE,
                "reason": "parity harness unavailable: missing "
                + ", ".join(missing) + " (owner stage = RTL generation; "
                "module = OrderingFSM)",
                "booksim": None, "rtl": None}
    from veritx_dse.backend.booksim_execution import (
        assert_execution_gate, parse_booksim_stats,
    )
    work = Path(rtl_dir).parent / "parity-smoke"
    work.mkdir(parents=True, exist_ok=True)
    trace = work / "workload.trace"
    trace.write_text(SMOKE_TRACE_TEXT)
    config = work / "parity.cfg"
    config.write_text(
        "topology = anynet;\n"
        f"network_file = {anynet};\n"
        "routing_function = min_anynet;\n"
        "traffic = trace(workload.trace);\n"
        "num_vcs = 2;\n"
        "vc_buf_size = 8;\n"
        "packet_size = 2;\n"
        "classes = 2;\n"
        "sim_type = throughput;\n"
        "sample_period = 10;\n"
        "warmup_periods = 0;\n"
        "print_activity = 0;\n")
    try:
        bproc = subprocess.run(
            [str(binary), "parity.cfg"], cwd=work,
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "NOT_RUN", "code": PARITY_UNAVAILABLE_CODE,
                "reason": f"parity harness unavailable: BookSim could not start "
                f"({exc}) (owner stage = RTL generation; module = OrderingFSM)",
                "booksim": None, "rtl": None}
    bstats = parse_booksim_stats(bproc.stdout, bproc.stderr)
    try:
        assert_execution_gate(bstats, expected_packets=5, expected_flits=10,
                              require_conservation=True)
    except Exception as exc:  # BookSimExecutionError: conservation breach
        return {"status": "FAIL", "code": PARITY_FAIL_CODE,
                "reason": f"BookSim conservation failed: {exc}",
                "booksim": {"delivered": bstats.get("delivered_packets"),
                            "flits_injected": bstats.get("flits_injected"),
                            "flits_accepted": bstats.get("flits_accepted")},
                "rtl": None}
    booksim_evidence = {
        "delivered": bstats.get("delivered_packets"),
        "injected_packets": bstats.get("injected_trace_packets"),
        "flits_injected": bstats.get("flits_injected"),
        "flits_accepted": bstats.get("flits_accepted"),
        "flits_by_class": bstats.get("flits_by_class"),
        # Drain = last-ejected-flit cycle; latency is per-class flit
        # latency (packet latency is typically empty for this trace).
        "drain_cycles": bstats.get("completion_cycles"),
        "latency_by_class": bstats.get("latency_by_class"),
    }
    # RTL side: build (make -j1 per caps) then run the emitted testbench
    # with the same trace file.
    rtl = Path(rtl_dir)
    if not (rtl / "noc_top.sv").is_file():
        return {"status": "FAIL", "code": PARITY_FAIL_CODE,
                "reason": f"RTL parity failed: {rtl}/noc_top.sv is missing",
                "booksim": booksim_evidence, "rtl": None}
    try:
        bproc2 = subprocess.run(["make", "-j1"], cwd=rtl,
                                capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "NOT_RUN", "code": PARITY_UNAVAILABLE_CODE,
                "reason": f"parity harness unavailable: RTL build could not start "
                f"({exc}) (owner stage = RTL generation; module = OrderingFSM)",
                "booksim": booksim_evidence, "rtl": None}
    if bproc2.returncode:
        return {"status": "FAIL", "code": PARITY_FAIL_CODE,
                "reason": "RTL parity failed: emitted testbench does not build: "
                + (bproc2.stdout + bproc2.stderr)[-2000:],
                "booksim": booksim_evidence, "rtl": None}
    import os
    env = dict(os.environ)
    env["NOC_TRACE_FILE"] = str(trace)
    env["NOC_TRACE_CYCLES"] = "100"
    try:
        rproc = subprocess.run(
            ["./obj_dir/Vnoc_top"], cwd=rtl, env=env,
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "FAIL", "code": PARITY_FAIL_CODE,
                "reason": f"RTL parity failed: testbench could not run ({exc})",
                "booksim": booksim_evidence, "rtl": None}
    output = (rproc.stdout or "") + (rproc.stderr or "")
    calibration = _parse_calibration_json(output)
    conserv_ok = "conservation:  5/5 pkts completed OK" in output
    drained = "outstanding:   0 OK" in output
    status_pass = "status: PASS" in output
    if (rproc.returncode != 0 or calibration is None or not conserv_ok
            or not drained or not status_pass):
        return {"status": "FAIL", "code": PARITY_FAIL_CODE,
                "reason": "RTL conservation failed (expected 5/5 packets, "
                "10/10 flits, exact drain): " + output[-2000:],
                "booksim": booksim_evidence,
                "rtl": {"completed": (calibration or {}).get("completed"),
                        "injected": (calibration or {}).get("injected"),
                        "ejected": (calibration or {}).get("ejected"),
                        "stuck": (calibration or {}).get("stuck"),
                        "returncode": rproc.returncode}}
    ejection_log = _parse_ejection_log(output)
    results_counts = _parse_results_counts(output)
    rtl_evidence = {
        "completed": calibration.get("completed"),
        "injected": calibration.get("injected"),
        "ejected": calibration.get("ejected"),
        "stuck": calibration.get("stuck"),
        "lat_mean": calibration.get("lat_mean"),
        "lat_p50": calibration.get("lat_p50"),
        "lat_p90": calibration.get("lat_p90"),
        "lat_p99": calibration.get("lat_p99"),
        "lat_max": calibration.get("lat_max"),
        "free_packets": results_counts.get("free_packets"),
        "esc_packets": results_counts.get("esc_packets"),
        "wrong_dst": results_counts.get("wrong_dst"),
        # Drain = last-ejection cycle (per-flit delivery log, cycle grain).
        "drain_cycles": (max(row["cyc"] for row in ejection_log)
                         if ejection_log else None),
        "ejection_log": ejection_log,
        "ejection_log_truncated": (
            calibration.get("ejected") is not None and
            len(ejection_log) < calibration.get("ejected")),
    }
    n_routers = _router_count_from_anynet(anynet)
    packets = _expected_packets_from_trace(trace.read_text(), n_routers)
    payloads = _compare_delivered_payloads(
        packets, ejection_log, calibration.get("ejected"))
    booksim_drain = booksim_evidence.get("drain_cycles")
    rtl_drain = rtl_evidence.get("drain_cycles")
    drain_delta = (booksim_drain - rtl_drain
                   if booksim_drain is not None and rtl_drain is not None
                   else None)
    # Latency populations differ by construction (BookSim per-class flit
    # latency vs TB packet head->tail latency): both are recorded, the
    # delta carries the population mismatch, and nothing is forced equal.
    per_class = (booksim_evidence.get("latency_by_class") or {})
    booksim_flit_lat = [round(float(block["flit_latency_avg"]), 3)
                        for block in per_class.values()
                        if "flit_latency_avg" in block]
    rtl_lat_mean = calibration.get("lat_mean")
    latency_delta = None
    if booksim_flit_lat and rtl_lat_mean is not None:
        latency_delta = round(float(sum(booksim_flit_lat)) / len(booksim_flit_lat)
                              - float(rtl_lat_mean), 3)
    cycle_accurate = {
        "drain_cycles": {"booksim": booksim_drain, "rtl": rtl_drain},
        "drain_delta_cycles": drain_delta,
        "cycle_exact": (drain_delta == 0),
        "latency": {
            "booksim_flit_latency_avgs_by_class": booksim_flit_lat,
            "rtl_packet_latency_mean": rtl_lat_mean,
            "delta": latency_delta,
            "scope": "populations differ (BookSim per-class average FLIT "
                     "latency vs TB packet head->tail latency); the delta "
                     "is informational, not an equality claim",
        },
        "n_routers": n_routers,
        "packet_count": len(packets),
    }
    if (booksim_evidence["delivered"] != rtl_evidence["completed"]
            or booksim_evidence["flits_accepted"] != rtl_evidence["ejected"]):
        return {"status": "FAIL", "code": PARITY_FAIL_CODE,
                "reason": "BookSim/RTL packet/flit counts do not agree on the "
                "same trace (parity breach)",
                "booksim": booksim_evidence, "rtl": rtl_evidence,
                "cycle_accurate": cycle_accurate,
                "delivered_payloads": payloads}
    if payloads.get("match") is not True:
        return {"status": "FAIL", "code": PARITY_FAIL_CODE,
                "reason": "RTL delivered-payload set does not match the "
                "trace-declared (src, dst, type) multiset (parity breach); "
                f"expected {payloads.get('expected_by_pair')} vs observed "
                f"{payloads.get('observed_by_pair')}",
                "booksim": booksim_evidence, "rtl": rtl_evidence,
                "cycle_accurate": cycle_accurate,
                "delivered_payloads": payloads}
    return {"status": "PASS", "code": PARITY_PASS_CODE,
            "reason": "BookSim and RTL deliver the same 5-packet / 10-flit "
            "trace with identical (src, dst, type) payload multisets "
            "(delivered==completed==5, accepted==ejected==10, exact drain). "
            "Cycle-accurate numbers are recorded (drain cycles, latency); "
            "observed cycle deltas are NOT forced equal "
            f"(drain delta = {drain_delta} cycles, cycle_exact="
            f"{cycle_accurate['cycle_exact']}).",
            "booksim": booksim_evidence, "rtl": rtl_evidence,
            "cycle_accurate": cycle_accurate,
            "delivered_payloads": payloads}


__all__ = [
    "EMITTED_VCS", "UNSUPPORTED_CODE", "OrderingEmission", "OrderingPolicy",
    "OrderingVerdict", "SMOKE_TRACE_TEXT", "build_ordering_fsm",
    "policy_from_request", "render_ordering_fsm",
    "run_booksim_rtl_parity_smoke",
    # Cycle-accurate parity helpers (manifest numbers + payload comparison).
    "_parse_ejection_log", "_parse_results_counts",
    "_expected_packets_from_trace", "_compare_delivered_payloads",
    "_router_count_from_anynet",
]
