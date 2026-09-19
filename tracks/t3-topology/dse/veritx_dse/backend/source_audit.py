"""veritx_dse.backend.source_audit — source-drift guard (B3.8a).

`booksim_profile.py` is the closed-world registry of configuration fields
the certified BookSim profile reads. It was built by hand. This module
makes the closure stay closed mechanically:

    scan the vendored BookSim sources for config.Get*/config->Get*("field")
        -> every read must be either
             * registered in the profile audit (active or inactive), or
             * listed in GATED_FIELDS with a gate that explains why it
               cannot affect the certified profile
        -> every registry/gated entry must still correspond to a real read
           (no stale entries hiding a removed read)

The gate vocabulary is machine-checkable where it can be:

    pin:<field>=<value>   the rendered certified config pins <field> to
                          <value>; verified against actual rendered bytes
    <mechanism tag>       a documented dispatch/presence mechanism whose
                          justification lives in MECHANISM_JUSTIFICATIONS

A new `config.GetInt("magic_knob")` anywhere in the fork therefore fails
the guard until someone registers it as active or states the gate. No C++
parser is needed: a conservative lexical scan is sufficient.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .booksim_profile import BOOKSIM_STANDALONE_PROFILE, ConfigRead

CONFIG_READ_RE = re.compile(
    r"config(?:->|\.)Get"
    r"(?:Int|Str|Float|IntArray|StrArray|FloatArray)"
    r"\s*\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"")


class SourceAuditError(ValueError):
    """The certified source closure diverges from the audit registry."""


# ── gated mechanisms ────────────────────────────────────────────────────

MECHANISM_JUSTIFICATIONS: dict[str, str] = {
    "diagnostic_only": (
        "selects an optional human-readable output file; the certified "
        "config never emits it, so the compiled empty default means no "
        "file and it cannot affect network results"),
    "trace_records": (
        "trace-driven packet length comes from each trace record; the "
        "certified runner validates every size against max_packet_flits "
        "and no config packet_size is emitted"),
    "pattern_dispatch": (
        "read only inside TrafficPattern::New branches for "
        "tornado/neighbor/badperm*/bad_dragon patterns (traffic.cpp); the "
        "certified targets render trace(...) or uniform, which do not "
        "reach those branches"),
    "conditional_presence": (
        "read only when config.GetIntMap().count(field) (veritx_embed.cpp:"
        "267-269); the certified projector never emits k/n/c"),
}


# Fields read by code that is unreachable for the certified profile.
# Every inactive registry entry also appears here with its gate so the
# gate is machine-checked rather than prose.
GATED_FIELDS: dict[str, tuple[str, ...]] = {
    "Cd": ("pin:sim_power=0",),
    "Cd_pwr": ("pin:sim_power=0",),
    "Cg": ("pin:sim_power=0",),
    "Cg_pwr": ("pin:sim_power=0",),
    "Cgdl": ("pin:sim_power=0",),
    "Cw_cpl": ("pin:sim_power=0",),
    "Cw_gnd": ("pin:sim_power=0",),
    "H_DFQD1": ("pin:sim_power=0",),
    "H_INVD2": ("pin:sim_power=0",),
    "H_ND2D1": ("pin:sim_power=0",),
    "H_SRAM": ("pin:sim_power=0",),
    "IoffN": ("pin:sim_power=0",),
    "IoffP": ("pin:sim_power=0",),
    "IoffSRAM": ("pin:sim_power=0",),
    "LAMBDA": ("pin:sim_power=0",),
    "MetalPitch": ("pin:sim_power=0",),
    "R": ("pin:sim_power=0",),
    "Rw": ("pin:sim_power=0",),
    "Vdd": ("pin:sim_power=0",),
    "W_DFQD1": ("pin:sim_power=0",),
    "W_INVD2": ("pin:sim_power=0",),
    "W_ND2D1": ("pin:sim_power=0",),
    "W_SRAM": ("pin:sim_power=0",),
    "channel_sweep": ("pin:sim_power=0",),
    "channel_width": ("pin:sim_power=0",),
    "power_output_file": ("pin:sim_power=0",),
    "tech_file": ("pin:sim_power=0",),
    "wire_length": ("pin:sim_power=0",),
    "batch_count": ("pin:sim_type=latency",),
    "batch_size": ("pin:sim_type=latency",),
    "max_outstanding_requests": ("pin:sim_type=latency",),
    "sent_packets_out": ("pin:sim_type=latency", "diagnostic_only"),
    "trace_file": ("pin:sim_type=latency",),
    "trace_packet_log": ("pin:sim_type=latency",),
    "const_flits_per_packet": ("pin:router=iq",),
    "multi_queue_size": ("pin:router=iq",),
    "vct": ("pin:router=iq",),
    "c": ("pin:topology=anynet", "conditional_presence"),
    "d": ("pin:topology=anynet",),
    "fail_seed": ("pin:topology=anynet",),
    "hybrid": ("pin:topology=anynet",),
    "k": ("pin:topology=anynet", "conditional_presence",
          "pattern_dispatch"),
    "mesh": ("pin:topology=anynet",),
    "n": ("pin:topology=anynet", "conditional_presence",
          "pattern_dispatch"),
    "o": ("pin:topology=anynet",),
    "use_noc_latency": ("pin:topology=anynet",),
    "x": ("pin:topology=anynet",),
    "xr": ("pin:topology=anynet", "pattern_dispatch"),
    "y": ("pin:topology=anynet",),
    "yr": ("pin:topology=anynet",),
    "burst_alpha": ("pin:injection_process=bernoulli",),
    "burst_beta": ("pin:injection_process=bernoulli",),
    "burst_r1": ("pin:injection_process=bernoulli",),
    "perm_seed": ("pattern_dispatch",),
    "packet_size": ("trace_records",),
    "packet_size_rate": ("trace_records",),
    "private_bufs": ("pin:buffer_policy=private",),
    "private_buf_size": ("pin:buffer_policy=private",),
    "private_buf_start_vc": ("pin:buffer_policy=private",),
    "private_buf_end_vc": ("pin:buffer_policy=private",),
    "max_held_slots": ("pin:buffer_policy=private",),
    "feedback_aging_scale": ("pin:buffer_policy=private",),
    "feedback_offset": ("pin:buffer_policy=private",),
    "write_fraction": ("pin:use_read_write=0",),
    "read_request_size": ("pin:use_read_write=0",),
    "read_reply_size": ("pin:use_read_write=0",),
    "write_request_size": ("pin:use_read_write=0",),
    "write_reply_size": ("pin:use_read_write=0",),
    "watch_out": ("diagnostic_only",),
    "watch_file": ("diagnostic_only",),
    "watch_flits": ("diagnostic_only",),
    "watch_packets": ("diagnostic_only",),
    "stats_out": ("diagnostic_only",),
    "injected_flits_out": ("diagnostic_only",),
    "received_flits_out": ("diagnostic_only",),
    "stored_flits_out": ("diagnostic_only",),
    "sent_flits_out": ("diagnostic_only",),
    "outstanding_credits_out": ("diagnostic_only",),
    "ejected_flits_out": ("diagnostic_only",),
    "active_packets_out": ("diagnostic_only",),
    "used_credits_out": ("diagnostic_only",),
    "free_credits_out": ("diagnostic_only",),
    "max_credits_out": ("diagnostic_only",),
}


# ── scanning ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceRead:
    field: str
    locations: tuple[str, ...]


@dataclass(frozen=True)
class DriftReport:
    reads: tuple[SourceRead, ...]
    unregistered: tuple[str, ...]
    stale_gated: tuple[str, ...]
    stale_registered: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not (self.unregistered or self.stale_gated
                    or self.stale_registered)

    def raise_if_dirty(self) -> None:
        if self.clean:
            return
        parts = []
        if self.unregistered:
            parts.append(
                "unregistered C++ config reads (register as active or "
                f"add a gate): {list(self.unregistered)}")
        if self.stale_gated:
            parts.append(
                f"gated fields no longer read: {list(self.stale_gated)}")
        if self.stale_registered:
            parts.append(
                f"registered fields no longer read: "
                f"{list(self.stale_registered)}")
        raise SourceAuditError("; ".join(parts))


def scan_config_reads(source_root: Path) -> tuple[SourceRead, ...]:
    """Conservative lexical scan of every .cpp/.hpp under source_root."""
    root = Path(source_root)
    found: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*")):
        if path.suffix not in (".cpp", ".hpp"):
            continue
        rel = str(path.relative_to(root))
        for line_no, line in enumerate(
                path.read_text(errors="ignore").splitlines(), 1):
            for match in CONFIG_READ_RE.finditer(line):
                found.setdefault(match.group(1), []).append(
                    f"{rel}:{line_no}")
    return tuple(SourceRead(field=name, locations=tuple(locs))
                 for name, locs in sorted(found.items()))


def audit_source_drift(
        source_root: Path,
        *,
        profile: Any = BOOKSIM_STANDALONE_PROFILE,
        gated: dict[str, tuple[str, ...]] = GATED_FIELDS,
) -> DriftReport:
    reads = scan_config_reads(source_root)
    read_fields = {r.field for r in reads}
    registry = set(profile.active_names()) | set(profile.inactive_names())
    unregistered = tuple(sorted(read_fields - registry - set(gated)))
    stale_gated = tuple(sorted(set(gated) - read_fields))
    stale_registered = tuple(sorted(registry - read_fields))
    return DriftReport(reads=reads, unregistered=unregistered,
                       stale_gated=stale_gated,
                       stale_registered=stale_registered)


# ── gate verification against a rendered certified config ───────────────

def parse_pin_gate(gate: str) -> tuple[str, str] | None:
    if not gate.startswith("pin:"):
        return None
    body = gate[len("pin:"):]
    if "=" not in body:
        raise SourceAuditError(f"malformed pin gate {gate!r}")
    field, value = body.split("=", 1)
    if not field:
        raise SourceAuditError(f"malformed pin gate {gate!r}")
    return field, value


def verify_gates(rendered_values: dict[str, str]) -> None:
    """Every gate must hold against the actual rendered certified config."""
    for field, gates in GATED_FIELDS.items():
        for gate in gates:
            pin = parse_pin_gate(gate)
            if pin is not None:
                name, value = pin
                if name not in rendered_values:
                    raise SourceAuditError(
                        f"gate for {field!r} names unpinned field {name!r}")
                if rendered_values[name] != value:
                    raise SourceAuditError(
                        f"gate {gate!r} for {field!r} does not hold: "
                        f"rendered {name}={rendered_values[name]!r}")
            elif gate not in MECHANISM_JUSTIFICATIONS:
                raise SourceAuditError(
                    f"field {field!r} uses unknown gate mechanism {gate!r}")


def gated_union(profile: Any = BOOKSIM_STANDALONE_PROFILE
                ) -> set[str]:
    return set(profile.inactive_names()) | {
        field for field, gates in GATED_FIELDS.items() if gates}


__all__ = [
    "CONFIG_READ_RE",
    "GATED_FIELDS",
    "MECHANISM_JUSTIFICATIONS",
    "DriftReport",
    "SourceAuditError",
    "SourceRead",
    "audit_source_drift",
    "gated_union",
    "parse_pin_gate",
    "scan_config_reads",
    "verify_gates",
]
