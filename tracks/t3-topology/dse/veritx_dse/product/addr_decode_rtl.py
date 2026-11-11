"""addr_decode_rtl — emit a real SystemVerilog decoder from the resolved map.

The compiler already resolves ``address_map.ranges`` into an
``AddressDecodeArtifact``: ranges to attached endpoints, IDENTITY transform,
ERROR on an unmatched address. This module renders that artifact as a
combinational decoder. It is deliberately not a router: it selects a target
endpoint and reports hit/miss/overlap.

Permission models:
  * Legacy range-keyed ``windows`` (PermissionWindow without identity) turn
    the decoder into a range firewall gated by ``req_write`` only. Without
    windows the rendered module is byte-identical to the historical decoder.
  * Initiator × region (preferred): ``initiator_policies`` carrying
    ``(agent_idx, address_range, readable, writable, atomic)`` keyed by
    ``(initiator, range)``. The module gains ``req_id`` (trusted
    ingress-asserted GROUP identity), keeps ``req_write``, adds optional
    ``req_atomic`` (only when some policy allows atomic), and ``burst_len``
    for full-burst containment. Default-deny: an initiator with no entry
    for the hit range is denied; an unknown ``req_id`` is denied; an
    unmapped address is a miss. Burst crossing a region boundary is DENIED
    (error completion), never split. Denied requests get ``allow=0``,
    ``perm_violation=1``, ``target_oh='0`` — never forwarded. The decoder
    is combinational with no state, so a denial strands no outstanding.

Initiator key = `agent_idx` (Agent GROUP). Tradeoff: one `req_id` per
group, smaller RTL than per-instance, but all instances of a group share
the group's policy. Identity is preserved from the NI/ingress port, never
inferred from drawing proximity.

Rationale: docs/decisions/modules/tools.md
"""
from __future__ import annotations

from typing import Any

ADDRESS_BITS = 64
_ADDRESS_LAST = (1 << ADDRESS_BITS) - 1


def _hex64(value: int) -> str:
    if type(value) is not int or value < 0 or value > _ADDRESS_LAST:
        raise ValueError(f"address decode value {value!r} is outside the 64-bit domain")
    return f"64'h{value:016x}"


def _bits_for_count(value: int) -> int:
    """Bits needed to hold 0..value inclusive."""
    return max(1, int(value).bit_length())


def _log2_pow2(value: int) -> int:
    if value < 1 or value & (value - 1):
        raise ValueError(f"{value!r} is not a positive power of two")
    return value.bit_length() - 1


def _entry_endpoints(entry: Any) -> tuple[int, ...]:
    ids = []
    if entry.target_endpoint_id is not None:
        ids.append(int(entry.target_endpoint_id))
    ids.extend(int(value) for value in entry.target_endpoint_ids)
    return tuple(ids)


def _entry_name(entry: Any, index: int) -> str:
    # A name is comment text, not RTL. Collapse every whitespace class so a
    # newline cannot escape the comment and inject a top-level statement.
    return " ".join(str(getattr(entry, "name", f"entry-{index}")).split()).replace("*/", "* /")


def _window_range(window: Any) -> str:
    name = getattr(window, "address_range", None)
    if name is None:
        name = getattr(window, "name", None)
    if name is None and isinstance(window, dict):
        name = window.get("address_range") or window.get("name")
    return name


def _window_flag(window: Any, key: str, default: bool = True) -> bool:
    if isinstance(window, dict):
        return window.get(key, default)
    return getattr(window, key, default)


def _window_initiator(window: Any) -> int | None:
    if isinstance(window, dict):
        v = window.get("agent_idx", window.get("initiator"))
        return int(v) if v is not None else None
    v = getattr(window, "agent_idx", None)
    if v is None:
        v = getattr(window, "initiator", None)
    return int(v) if v is not None else None


def _window_atomic(window: Any) -> bool:
    if isinstance(window, dict):
        return bool(window.get("atomic", False))
    return bool(getattr(window, "atomic", False))


def _window_instance(window: Any) -> int | None:
    if isinstance(window, dict):
        v = window.get("instance_idx")
        return int(v) if v is not None else None
    v = getattr(window, "instance_idx", None)
    return int(v) if v is not None else None


def _window_permission_map(entries: Any, windows: Any) -> dict:
    """Map entry index -> (readable, writable) for windowed entries."""
    windowed: dict[str, tuple[bool, bool]] = {}
    for window in windows or ():
        name = _window_range(window)
        if not name:
            raise ValueError(f"permission window has no address_range: {window!r}")
        if name in windowed:
            raise ValueError(f"duplicate permission window for range {name!r}")
        windowed[name] = (bool(_window_flag(window, "readable", True)),
                          bool(_window_flag(window, "writable", True)))
    known = {getattr(entry, "name", None) for entry in entries}
    for name in windowed:
        if name not in known:
            raise ValueError(
                f"permission window names unknown address range {name!r}; "
                f"declared ranges are {sorted(known)}")
    return {index: windowed[getattr(entry, "name", None)]
            for index, entry in enumerate(entries)
            if getattr(entry, "name", None) in windowed}


def _initiator_permission_map(entries: Any, policies: Any) -> dict:
    by_range: dict[str, dict[int, tuple[bool, bool, bool]]] = {}
    for p in policies or ():
        if _window_instance(p) is not None:
            continue
        name = _window_range(p)
        if not name:
            raise ValueError(f"initiator policy has no address_range: {p!r}")
        init = _window_initiator(p)
        if init is None:
            raise ValueError(
                f"initiator policy for range {name!r} has no "
                f"agent_idx identity: {p!r}")
        if init < 0:
            raise ValueError(
                f"initiator policy for range {name!r} has negative "
                f"agent_idx {init}")
        readable = bool(_window_flag(p, "readable", True))
        writable = bool(_window_flag(p, "writable", True))
        atomic = _window_atomic(p)
        slot = by_range.setdefault(name, {})
        if init in slot:
            raise ValueError(
                f"duplicate initiator permission policy for "
                f"(initiator {init}, range {name!r})")
        slot[int(init)] = (readable, writable, atomic)
    known = {getattr(entry, "name", None) for entry in entries}
    for name in by_range:
        if name not in known:
            raise ValueError(
                f"permission window names unknown address range {name!r}; "
                f"declared ranges are {sorted(known)}")
    return {index: by_range.get(getattr(entry, "name", None), {})
            for index, entry in enumerate(entries)
            if getattr(entry, "name", None) in by_range}


def _initiator_instance_map(entries: Any, policies: Any) -> dict:
    by_range: dict[str, dict[tuple[int, int], tuple[bool, bool, bool]]] = {}
    for p in policies or ():
        inst = _window_instance(p)
        if inst is None:
            continue
        name = _window_range(p)
        if not name:
            raise ValueError(f"initiator policy has no address_range: {p!r}")
        init = _window_initiator(p)
        if init is None:
            raise ValueError(
                f"initiator policy for range {name!r} has no "
                f"agent_idx identity: {p!r}")
        readable = bool(_window_flag(p, "readable", True))
        writable = bool(_window_flag(p, "writable", True))
        atomic = _window_atomic(p)
        slot = by_range.setdefault(name, {})
        if (int(init), int(inst)) in slot:
            raise ValueError(
                f"duplicate initiator permission policy for "
                f"(initiator {init}, instance {inst}, range {name!r})")
        slot[(int(init), int(inst))] = (readable, writable, atomic)
    known = {getattr(entry, "name", None) for entry in entries}
    for name in by_range:
        if name not in known:
            raise ValueError(
                f"permission window names unknown address range {name!r}; "
                f"declared ranges are {sorted(known)}")
    groups: dict[tuple[str, int], tuple[bool, bool, bool]] = {}
    for p in policies or ():
        if _window_instance(p) is not None:
            continue
        groups[(_window_range(p), _window_initiator(p))] = (
            bool(_window_flag(p, "readable", True)),
            bool(_window_flag(p, "writable", True)),
            _window_atomic(p))
    for name, slot in by_range.items():
        for (init, inst), (r, w, a) in slot.items():
            if (name, init) not in groups:
                raise ValueError(
                    f"instance policy (initiator {init}, instance {inst}, "
                    f"range {name!r}) has no group policy to narrow")
            gr, gw, ga = groups[(name, init)]
            if (r and not gr) or (w and not gw) or (a and not ga):
                raise ValueError(
                    f"instance policy (initiator {init}, instance {inst}, "
                    f"range {name!r}) widens group rights: readable={r} "
                    f"writable={w} atomic={a} exceed group readable={gr} "
                    f"writable={gw} atomic={ga}")
    return {index: by_range.get(getattr(entry, "name", None), {})
            for index, entry in enumerate(entries)
            if getattr(entry, "name", None) in by_range}


def render_addr_decode(decode: Any, *, module: str = "addr_decode",
                       addr_width: int = ADDRESS_BITS, windows: Any = (),
                       initiator_policies: Any = ()) -> str:
    """Render one combinational address decoder.

    ``decode`` is an ``AddressDecodeArtifact`` (duck-typed so this module does
    not import the model layer). Every entry's target endpoint ids must fit in
    the emitted one-hot vector; the compiler already validated the selection
    policy, alignment and overlap rules.

    Legacy ``windows`` are the STAGE 1 ``PermissionWindow`` declarations
    (duck-typed ``address_range``/``readable``/``writable``). With windows the
    ports gain ``req_write``/``allow``/``perm_violation`` and ``target_oh`` is
    gated to allowed hits only.

    ``initiator_policies`` are ``InitiatorPolicy``-shaped (duck-typed
    ``agent_idx``/``address_range``/``readable``/``writable``/``atomic``).
    When present — or when ``windows`` carries an ``agent_idx`` — the
    renderer keys by ``(initiator, range)`` and emits ``req_id`` +
    ``burst_len`` (+ ``req_atomic`` when some policy allows atomic) with
    default-deny and burst-DENY semantics. Without any policy the output is
    byte-identical to the historical decoder.
    """
    if not 1 <= addr_width <= ADDRESS_BITS:
        raise ValueError(f"addr_width must be 1..{ADDRESS_BITS}, got {addr_width}")
    entries = tuple(getattr(decode, "entries", ()) or ())
    # Unify policy carriers. `windows` may hold legacy PermissionWindow
    # (no agent_idx) or InitiatorPolicy; `initiator_policies` is explicit.
    raw_policies = tuple(windows or ()) + tuple(initiator_policies or ())
    has_initiator = any(_window_initiator(w) is not None for w in raw_policies)
    if has_initiator:
        imap = _initiator_permission_map(entries, raw_policies)
        permissions: dict = {}
        has_windows = bool(imap) or bool(raw_policies)
    else:
        permissions = _window_permission_map(entries, tuple(windows or ()) + tuple(initiator_policies or ()))
        imap: dict = {}
        has_windows = bool(permissions)
    endpoint_ids = sorted({endpoint for entry in entries for endpoint in _entry_endpoints(entry)})
    n_endpoints = (max(endpoint_ids) + 1) if endpoint_ids else 1
    n_entries = len(entries)
    has_striped = any(getattr(entry, "selection_policy", None) == "STRIPED" for entry in entries)
    decode_hash = getattr(decode, "address_decode_hash", "") or ""

    if has_windows and has_initiator:
        lines = [
            "// addr_decode.sv — generated from the resolved AddressDecodeArtifact.",
            "// IDENTITY address transform; ERROR on an unmatched address.",
            "// This module selects an attached endpoint and enforces the",
            "// declared STAGE 1 initiator × region permission policies:",
            "// req_id (trusted ingress-asserted GROUP identity) + req_write",
            "// (+ req_atomic when a policy allows atomic) select the policy",
            "// for the hit range. Default-deny: a missing (initiator, range)",
            "// entry or an unknown req_id denies. A burst whose extent is not",
            "// fully inside the hit range is DENIED (never split, never",
            "// forwarded): burst_len==0 is a single access.",
            "// Denied/invalid requests raise perm_violation with no endpoint",
            "// selected and strand no outstanding (combinational, no state).",
        ]
    elif has_windows:
        lines = [
            "// addr_decode.sv — generated from the resolved AddressDecodeArtifact.",
            "// IDENTITY address transform; ERROR on an unmatched address.",
            "// This module selects an attached endpoint and enforces the",
            "// declared STAGE 1 permission windows: a hit denied on the",
            "// requested side (req_write selects it) raises perm_violation",
            "// and selects no endpoint. It does not implement protocol",
            "// adaptation or packet routing.",
        ]
    else:
        lines = [
            "// addr_decode.sv — generated from the resolved AddressDecodeArtifact.",
            "// IDENTITY address transform; ERROR on an unmatched address.",
            "// This module selects an attached endpoint. It is not a firewall and",
            "// does not implement protocol permissions, adaptation or routing.",
        ]
    # ---- Initiator mode: a distinct module shape -----------------------
    if has_windows and has_initiator and n_entries != 0:
        # Collect initiator ids and whether atomic is ever allowed.
        all_inits = sorted({int(_window_initiator(w)) for w in raw_policies
                            if _window_initiator(w) is not None})
        max_init = max(all_inits) if all_inits else 0
        req_id_w = _bits_for_count(max_init)
        imap2 = _initiator_instance_map(entries, raw_policies)
        all_insts = sorted({k[1] for slot in imap2.values() for k in slot})
        has_instance = bool(all_insts)
        req_inst_w = _bits_for_count(max(all_insts)) if all_insts else 1
        has_atomic = any(_window_atomic(w) for w in raw_policies)
        burst_w = 16
        lines.extend([
            f"// address_decode_hash: {decode_hash or 'not supplied'}",
            "`default_nettype none",
            "",
            f"module {module} #(",
            f"  parameter int ADDR_W = {addr_width},",
            f"  parameter int REQ_ID_W = {req_id_w},",
        ])
        if has_instance:
            lines.append(f"  parameter int REQ_INST_W = {req_inst_w},")
        lines.extend([
            f"  parameter int BURST_W = {burst_w},",
            f"  parameter int N_ENDPOINTS = {n_endpoints},",
            "  parameter int PERM_VIOLATION_TIMING_SIDE_CHANNEL_DECLARED = 1",
            ") (",
            "  input  logic [ADDR_W-1:0]      addr,",
            "  input  logic [REQ_ID_W-1:0]    req_id,",
            "  input  logic                   req_write,",
        ])
        if has_instance:
            lines.append("  input  logic [REQ_INST_W-1:0]    req_inst = '0,")
        lines.append("  input  logic [REQ_ID_W-1:0]    wire_req_id = '0,")
        if has_instance:
            lines.append("  input  logic [REQ_INST_W-1:0]    wire_req_inst = '0,")
        if has_atomic:
            lines.append("  input  logic                   req_atomic,")
        lines.extend([
            "  input  logic [BURST_W-1:0]     burst_len,",
            "  output logic [N_ENDPOINTS-1:0] target_oh,",
            "  output logic                   hit,",
            "  output logic                   miss,",
            "  output logic                   overlap,",
            "  output logic                   allow,",
            "  output logic                   perm_violation,",
            "  output logic                   wire_identity_mismatch,",
            "  output logic                   timing_side_channel_declared,",
            "  output logic                   burst_violation",
            ");",
            "",
        ])
        hit_width = _bits_for_count(n_entries)
        lines.extend([
            f"  localparam int N_ENTRIES = {n_entries};",
            f"  localparam int HIT_W = {hit_width};",
            "  logic [63:0] addr64;",
            "  logic [63:0] burst_end;",
            "  logic [N_ENTRIES-1:0] entry_hit;",
            "  logic [N_ENTRIES-1:0] entry_burst_ok;",
            "  logic [N_ENTRIES-1:0] entry_perm_ok;",
            "  logic [N_ENTRIES-1:0] entry_allow;",
            "  logic [HIT_W-1:0] hit_count;",
        ])
        if has_atomic:
            lines.append("  logic [N_ENTRIES-1:0] entry_atomic_ok;")
        if has_instance:
            lines.append("  logic [N_ENTRIES-1:0] entry_inst_perm_ok;")
        if has_instance and has_atomic:
            lines.append("  logic [N_ENTRIES-1:0] entry_inst_atomic_ok;")
        if has_striped:
            lines.append("  logic [63:0] stripe_index;")
        lines.extend([
            "",
            "  assign addr64 = 64'(addr);",
            "  assign burst_end = addr64 + ((burst_len == 0) ? 64'd0 : (64'(burst_len) - 64'd1));",
            "",
        ])
        for index, entry in enumerate(entries):
            base = int(entry.base)
            last = base + int(entry.size) - 1
            policy = getattr(entry, "selection_policy", None)
            lines.append(f"  // entry {index}: {_entry_name(entry, index)}")
            if base != 0 or policy == "STRIPED":
                lines.append(f"  localparam logic [63:0] BASE_{index} = {_hex64(base)};")
            if last != _ADDRESS_LAST:
                lines.append(f"  localparam logic [63:0] LAST_{index} = {_hex64(last)};")
            if base == 0 and last == _ADDRESS_LAST:
                lines.append(f"  assign entry_hit[{index}] = 1'b1;")
            elif base == 0:
                lines.append(f"  assign entry_hit[{index}] = (addr64 <= LAST_{index});")
            elif last == _ADDRESS_LAST:
                lines.append(f"  assign entry_hit[{index}] = (addr64 >= BASE_{index});")
            else:
                lines.append(f"  assign entry_hit[{index}] = (addr64 >= BASE_{index}) && (addr64 <= LAST_{index});")
            # Burst containment: fully inside the hit range, else DENY.
            if base == 0 and last == _ADDRESS_LAST:
                lines.append(
                    f"  assign entry_burst_ok[{index}] = "
                    f"entry_hit[{index}] && (burst_len == 0 || burst_end >= addr64);")
            elif base == 0:
                lines.append(
                    f"  assign entry_burst_ok[{index}] = "
                    f"entry_hit[{index}] && ((burst_len == 0) || "
                    f"((burst_end >= addr64) && (burst_end <= LAST_{index})));")
            elif last == _ADDRESS_LAST:
                lines.append(
                    f"  assign entry_burst_ok[{index}] = "
                    f"entry_hit[{index}] && ((burst_len == 0) || "
                    f"(burst_end >= addr64));")
            else:
                lines.append(
                    f"  assign entry_burst_ok[{index}] = "
                    f"entry_hit[{index}] && ((burst_len == 0) || "
                    f"((burst_end >= addr64) && (burst_end <= LAST_{index})));")
            # Default-deny placeholder; real gating below (driven by the
            # per-initiator case, not by a continuous assign).
            lines.append(
                f"  // permission (STAGE 1 M1, initiator x range): "
                f"{_entry_name(entry, index)} default-deny")
            lines.append("")
        # Per-initiator policy decode (one case covering every entry).
        lines.extend([
            "  always_comb begin",
            "    entry_perm_ok = '0;",
            ("    entry_atomic_ok = '0;" if has_atomic else "    // entry_atomic_ok omitted (no atomic policy)"),
            "    case (req_id)",
        ])
        # Default case already denied ('0 above); each known initiator sets
        # its per-entry bits. Unknown req_id stays denied.
        for init in all_inits:
            lines.append(f"      {req_id_w}'d{init}: begin")
            for index, entry in enumerate(entries):
                pol = imap.get(index, {}).get(init)
                if pol is None:
                    lines.append(f"        entry_perm_ok[{index}] = 1'b0;")
                    if has_atomic:
                        lines.append(f"        entry_atomic_ok[{index}] = 1'b0;")
                    continue
                readable, writable, atomic_bit = pol
                readable_lit = "1'b1" if readable else "1'b0"
                writable_lit = "1'b1" if writable else "1'b0"
                atomic_lit = "1'b1" if atomic_bit else "1'b0"
                lines.append(
                    f"        // initiator {init}: readable={1 if readable else 0} "
                    f"writable={1 if writable else 0} atomic={1 if atomic_bit else 0}")
                lines.append(
                    f"        entry_perm_ok[{index}] = (req_write ? {writable_lit} : {readable_lit});")
                if has_atomic:
                    lines.append(
                        f"        entry_atomic_ok[{index}] = {atomic_lit};")
            lines.append("      end")
        lines.extend([
            "      default: begin",
            "        entry_perm_ok = '0;",
            ("        entry_atomic_ok = '0;" if has_atomic else "        // no atomic"),
            "      end",
            "    endcase",
            "  end",
            "",
        ])
        if has_instance:
            lines.extend(["  always_comb begin"])
            for index in range(n_entries):
                lines.append(f"    entry_inst_perm_ok[{index}] = 1'b1;")
                if has_atomic:
                    lines.append(f"    entry_inst_atomic_ok[{index}] = 1'b1;")
            for index, slot in sorted(imap2.items()):
                for (aidx, iidx), (r, w, at) in sorted(slot.items()):
                    lines.append(
                        f"    if (req_id == {req_id_w}'d{aidx} && req_inst == {req_inst_w}'d{iidx}) begin")
                    lines.append(
                        f"      entry_inst_perm_ok[{index}] = (req_write ? "
                        f"{'1\'b1' if w else '1\'b0'} : {'1\'b1' if r else '1\'b0'});")
                    if has_atomic:
                        lines.append(
                            f"      entry_inst_atomic_ok[{index}] = "
                            f"{'1\'b1' if at else '1\'b0'};")
                    lines.append("    end")
            lines.extend(["  end", ""])
        if has_atomic:
            for index in range(n_entries):
                if has_instance:
                    lines.append(
                        f"  assign entry_allow[{index}] = entry_hit[{index}] "
                        f"&& entry_perm_ok[{index}] && entry_inst_perm_ok[{index}] "
                        f"&& entry_burst_ok[{index}] "
                        f"&& (!req_atomic || (entry_atomic_ok[{index}] "
                        f"&& entry_inst_atomic_ok[{index}]));")
                else:
                    lines.append(
                        f"  assign entry_allow[{index}] = entry_hit[{index}] "
                        f"&& entry_perm_ok[{index}] && entry_burst_ok[{index}] "
                        f"&& (!req_atomic || entry_atomic_ok[{index}]);")
        else:
            for index in range(n_entries):
                if has_instance:
                    lines.append(
                        f"  assign entry_allow[{index}] = entry_hit[{index}] "
                        f"&& entry_perm_ok[{index}] && entry_inst_perm_ok[{index}] "
                        f"&& entry_burst_ok[{index}];")
                else:
                    lines.append(
                        f"  assign entry_allow[{index}] = entry_hit[{index}] "
                        f"&& entry_perm_ok[{index}] && entry_burst_ok[{index}];")
        lines.append("")
        lines.extend([
            "  always_comb begin",
            "    target_oh = '0;",
            "    hit_count = '0;",
        ])
        if has_striped:
            lines.append("    stripe_index = '0;")
        lines.append("    for (int i = 0; i < N_ENTRIES; i++) hit_count += entry_hit[i];")
        for index, entry in enumerate(entries):
            policy = getattr(entry, "selection_policy", None)
            lines.append(f"    if (entry_allow[{index}]) begin")
            if policy == "STRIPED":
                endpoints = _entry_endpoints(entry)
                interleave = int(entry.interleave_bytes)
                log2_interleave = _log2_pow2(interleave)
                lines.extend([
                    f"      // striped across {len(endpoints)} endpoint(s), {interleave} byte interleave",
                    f"      stripe_index = (addr64 - BASE_{index}) >> {log2_interleave};",
                    f"      case (stripe_index % {len(endpoints)})",
                ])
                for stripe, endpoint in enumerate(endpoints):
                    lines.append(f"        {stripe}: target_oh[{endpoint}] = 1'b1;")
                lines.append(f"        default: target_oh[{endpoints[0]}] = 1'b1;")
                lines.append("      endcase")
            else:
                endpoint = entry.target_endpoint_id
                if endpoint is None:
                    raise ValueError(f"entry {index!r} has no target endpoint and is not STRIPED")
                lines.append(f"      target_oh[{int(endpoint)}] = 1'b1;")
            lines.append("    end")
        lines.extend([
            "  end",
            "",
            "  // target_oh is one-hot only while overlap is low. The compiler refuses",
            "  // overlapping ranges, so overlap is a structural assertion, not a",
            "  // normal routing mode.",
            "  assign hit     = |entry_hit;",
            "  assign miss    = ~hit;",
            "  assign overlap = (hit_count > 1);",
            "  // Permission (STAGE 1 M1): allow is set only on an allowed hit;",
            "  // perm_violation names a hit denied on the requested side or a",
            "  // burst/atomic violation. Denied requests select no endpoint.",
            "  assign allow = |entry_allow;",
            "  assign perm_violation = hit && !allow;",
        ])
        if has_instance:
            lines.append(
                "  assign wire_identity_mismatch = (wire_req_id != req_id) "
                "|| (wire_req_inst != req_inst);")
        else:
            lines.append(
                "  assign wire_identity_mismatch = (wire_req_id != req_id);")
        lines.extend([
            "  assign burst_violation = hit && !(|(entry_hit & entry_burst_ok));",
            "  assign timing_side_channel_declared = "
            "PERM_VIOLATION_TIMING_SIDE_CHANNEL_DECLARED[0];",
            "endmodule",
            "`default_nettype wire",
            "",
        ])
        return "\n".join(lines)

    # ---- Legacy paths (byte-identical historical output) ---------------
    lines.extend([
        f"// address_decode_hash: {decode_hash or 'not supplied'}",
        "`default_nettype none",
        "",
        f"module {module} #(",
        f"  parameter int ADDR_W = {addr_width},",
        f"  parameter int N_ENDPOINTS = {n_endpoints}",
        ") (",
    ])
    if n_entries == 0:
        # No range exists to window (M1 refuses windows that name unknown
        # ranges); keep the historical miss decoder byte-identical.
        lines.extend([
            "  /* verilator lint_off UNUSEDSIGNAL */",
            "  input  logic [ADDR_W-1:0]      addr,",
            "  /* verilator lint_on UNUSEDSIGNAL */",
        ])
    else:
        lines.append("  input  logic [ADDR_W-1:0]      addr,")
        if has_windows:
            lines.append("  input  logic                   req_write,")
    lines.extend([
        "  output logic [N_ENDPOINTS-1:0] target_oh,",
        "  output logic                   hit,",
        "  output logic                   miss,",
        "  output logic                   overlap"
        + ("," if has_windows else ""),
    ])
    if has_windows:
        lines.extend([
            "  output logic                   allow,",
            "  output logic                   perm_violation",
        ])
    lines.extend([");", ""])

    if n_entries == 0:
        lines.extend([
            "  // No range is declared. An empty map is a decode miss, never a",
            "  // silent pass-through to an arbitrary endpoint.",
            "  assign target_oh = '0;",
            "  assign hit       = 1'b0;",
            "  assign miss      = 1'b1;",
            "  assign overlap   = 1'b0;",
            "endmodule",
            "`default_nettype wire",
            "",
        ])
        return "\n".join(lines)

    hit_width = _bits_for_count(n_entries)
    lines.extend([
        f"  localparam int N_ENTRIES = {n_entries};",
        f"  localparam int HIT_W = {hit_width};",
        "  logic [63:0] addr64;",
        "  logic [N_ENTRIES-1:0] entry_hit;",
        "  logic [HIT_W-1:0] hit_count;",
    ])
    if has_windows:
        lines.append("  logic [N_ENTRIES-1:0] entry_allow;")
    if has_striped:
        lines.append("  logic [63:0] stripe_index;")
    lines.extend([
        "",
        "  assign addr64 = 64'(addr);",
        "",
    ])
    for index, entry in enumerate(entries):
        base = int(entry.base)
        last = base + int(entry.size) - 1
        policy = getattr(entry, "selection_policy", None)
        lines.append(f"  // entry {index}: {_entry_name(entry, index)}")
        if base != 0 or policy == "STRIPED":
            lines.append(f"  localparam logic [63:0] BASE_{index} = {_hex64(base)};")
        if last != _ADDRESS_LAST:
            lines.append(f"  localparam logic [63:0] LAST_{index} = {_hex64(last)};")
        if base == 0 and last == _ADDRESS_LAST:
            lines.append(f"  assign entry_hit[{index}] = 1'b1;")
        elif base == 0:
            lines.append(f"  assign entry_hit[{index}] = (addr64 <= LAST_{index});")
        elif last == _ADDRESS_LAST:
            lines.append(f"  assign entry_hit[{index}] = (addr64 >= BASE_{index});")
        else:
            lines.append(f"  assign entry_hit[{index}] = (addr64 >= BASE_{index}) && (addr64 <= LAST_{index});")
        if has_windows:
            if index in permissions:
                readable, writable = permissions[index]
                lines.append(
                    f"  // permission (STAGE 1 M1): {_entry_name(entry, index)} "
                    f"readable={1 if readable else 0} writable="
                    f"{1 if writable else 0}")
                readable_lit = "1'b1" if readable else "1'b0"
                writable_lit = "1'b1" if writable else "1'b0"
                lines.append(
                    f"  assign entry_allow[{index}] = entry_hit[{index}] "
                    f"&& (req_write ? {writable_lit} : {readable_lit});")
            else:
                lines.append(
                    f"  assign entry_allow[{index}] = entry_hit[{index}];")
        lines.append("")

    lines.extend([
        "  always_comb begin",
        "    target_oh = '0;",
        "    hit_count = '0;",
    ])
    if has_striped:
        lines.append("    stripe_index = '0;")
    lines.append("    for (int i = 0; i < N_ENTRIES; i++) hit_count += entry_hit[i];")
    for index, entry in enumerate(entries):
        policy = getattr(entry, "selection_policy", None)
        gate = f"entry_allow[{index}]" if has_windows else f"entry_hit[{index}]"
        lines.append(f"    if ({gate}) begin")
        if policy == "STRIPED":
            endpoints = _entry_endpoints(entry)
            interleave = int(entry.interleave_bytes)
            log2_interleave = _log2_pow2(interleave)
            lines.extend([
                f"      // striped across {len(endpoints)} endpoint(s), {interleave} byte interleave",
                f"      stripe_index = (addr64 - BASE_{index}) >> {log2_interleave};",
                f"      case (stripe_index % {len(endpoints)})",
            ])
            for stripe, endpoint in enumerate(endpoints):
                lines.append(f"        {stripe}: target_oh[{endpoint}] = 1'b1;")
            lines.append(f"        default: target_oh[{endpoints[0]}] = 1'b1;")
            lines.append("      endcase")
        else:
            endpoint = entry.target_endpoint_id
            if endpoint is None:
                raise ValueError(f"entry {index!r} has no target endpoint and is not STRIPED")
            lines.append(f"      target_oh[{int(endpoint)}] = 1'b1;")
        lines.append("    end")
    lines.extend([
        "  end",
        "",
        "  // target_oh is one-hot only while overlap is low. The compiler refuses",
        "  // overlapping ranges, so overlap is a structural assertion, not a",
        "  // normal routing mode.",
        "  assign hit     = |entry_hit;",
        "  assign miss    = ~hit;",
        "  assign overlap = (hit_count > 1);",
    ])
    if has_windows:
        lines.extend([
            "  // Permission (STAGE 1 M1): allow is set only on an allowed hit;",
            "  // perm_violation names a hit denied on the requested side.",
            "  assign allow = |entry_allow;",
            "  assign perm_violation = hit && !allow;",
        ])
    lines.extend(["endmodule", "`default_nettype wire", ""])
    return "\n".join(lines)


__all__ = ["render_addr_decode"]
