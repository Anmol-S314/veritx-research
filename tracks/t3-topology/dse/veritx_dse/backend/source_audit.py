"""veritx_dse.backend.source_audit — read-site-aware source-drift guard
(B3.8a, hardened in B3.8e).

`booksim_profile.py` is the closed-world registry of configuration fields
the certified BookSim profile reads. This module makes the closure stay
closed mechanically and PER READ SITE:

    scan the vendored BookSim sources (whole-file lexical scan, so
    multiline calls cannot evade it) for
        config.Get*/config->Get*("field")
        -> for every discovered (field, source file):
             * field is registered active in the profile registry, OR
             * (field, file) is covered by GATED_FIELDS + GATED_SCOPE:
               the field's gate must hold for that specific file
        -> stale registry entries, stale gates, stale scopes and
           uncovered read sites are refused.

Gating a field name is not enough: a new read of an already-gated field
from a different file (e.g. channel_width in the power module today,
someone adding it to iq_router.cpp tomorrow) fails until that read site
is explicitly registered or gated.

Scope note: this audits the STANDALONE certified fork
(third_party/booksim2/src). The embedded serving mirror
(third_party/astra-sim/extern/network_backend/booksim2/booksim2/src) is
covered by an explicit read-site identity check (see tests); full
embedded-source drift qualification is deferred until SERVING_BOOKSIM2
receives an authoritative ResolvedFabric bridge and becomes executable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .booksim_profile import BOOKSIM_STANDALONE_PROFILE, ConfigRead

# Whole-file scan: whitespace/newlines may appear around the arrow and
# between the getter and its argument, so multiline calls are found too.
CONFIG_READ_RE = re.compile(
    r"config\s*(?:->|\.)\s*Get"
    r"(?:Int|Str|Float|IntArray|StrArray|FloatArray)"
    r"\s*\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"")
CONFIG_READ_GROUP = 1


class SourceAuditError(ValueError):
    """The certified source closure diverges from the audit registry."""


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


# ── gated fields and their allowed read sites ───────────

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

GATED_SCOPE: dict[str, tuple[str, ...]] = {
    'Cd': ('power/power_module.cpp',),
    'Cd_pwr': ('power/power_module.cpp',),
    'Cg': ('power/power_module.cpp',),
    'Cg_pwr': ('power/power_module.cpp',),
    'Cgdl': ('power/power_module.cpp',),
    'Cw_cpl': ('power/power_module.cpp',),
    'Cw_gnd': ('power/power_module.cpp',),
    'H_DFQD1': ('power/power_module.cpp',),
    'H_INVD2': ('power/power_module.cpp',),
    'H_ND2D1': ('power/power_module.cpp',),
    'H_SRAM': ('power/power_module.cpp',),
    'IoffN': ('power/power_module.cpp',),
    'IoffP': ('power/power_module.cpp',),
    'IoffSRAM': ('power/power_module.cpp',),
    'LAMBDA': ('power/power_module.cpp',),
    'MetalPitch': ('power/power_module.cpp',),
    'R': ('power/power_module.cpp',),
    'Rw': ('power/power_module.cpp',),
    'Vdd': ('power/power_module.cpp',),
    'W_DFQD1': ('power/power_module.cpp',),
    'W_INVD2': ('power/power_module.cpp',),
    'W_ND2D1': ('power/power_module.cpp',),
    'W_SRAM': ('power/power_module.cpp',),
    'active_packets_out': ('trafficmanager.cpp',),
    'batch_count': ('batchtrafficmanager.cpp',),
    'batch_size': ('batchtrafficmanager.cpp',),
    'burst_alpha': ('injection.cpp',),
    'burst_beta': ('injection.cpp',),
    'burst_r1': ('injection.cpp',),
    'c': ('networks/cmesh.cpp', 'networks/flatfly_onchip.cpp', 'networks/gec.cpp', 'veritx_embed.cpp'),
    'channel_sweep': ('power/power_module.cpp',),
    'channel_width': ('power/power_module.cpp',),
    'const_flits_per_packet': ('routers/chaos_router.cpp',),
    'd': ('networks/gec.cpp',),
    'ejected_flits_out': ('trafficmanager.cpp',),
    'fail_seed': ('networks/kncube.cpp',),
    'feedback_aging_scale': ('buffer_state.cpp',),
    'feedback_offset': ('buffer_state.cpp',),
    'free_credits_out': ('trafficmanager.cpp',),
    'hybrid': ('networks/gec.cpp',),
    'injected_flits_out': ('trafficmanager.cpp',),
    'k': ('networks/cmesh.cpp', 'networks/dragonfly.cpp', 'networks/fattree.cpp', 'networks/flatfly_onchip.cpp', 'networks/fly.cpp', 'networks/gec.cpp', 'networks/kncube.cpp', 'networks/qtree.cpp', 'networks/tree4.cpp', 'traffic.cpp', 'veritx_embed.cpp'),
    'max_credits_out': ('trafficmanager.cpp',),
    'max_held_slots': ('buffer_state.cpp',),
    'max_outstanding_requests': ('batchtrafficmanager.cpp',),
    'mesh': ('networks/gec.cpp',),
    'multi_queue_size': ('routers/chaos_router.cpp',),
    'n': ('networks/cmesh.cpp', 'networks/dragonfly.cpp', 'networks/fattree.cpp', 'networks/flatfly_onchip.cpp', 'networks/fly.cpp', 'networks/kncube.cpp', 'networks/qtree.cpp', 'networks/tree4.cpp', 'traffic.cpp', 'veritx_embed.cpp'),
    'o': ('networks/gec.cpp',),
    'outstanding_credits_out': ('trafficmanager.cpp',),
    'packet_size': ('trafficmanager.cpp',),
    'packet_size_rate': ('trafficmanager.cpp',),
    'perm_seed': ('traffic.cpp',),
    'power_output_file': ('power/power_module.cpp',),
    'private_buf_end_vc': ('buffer_state.cpp',),
    'private_buf_size': ('buffer_state.cpp',),
    'private_buf_start_vc': ('buffer_state.cpp',),
    'private_bufs': ('buffer_state.cpp',),
    'read_reply_size': ('trafficmanager.cpp',),
    'read_request_size': ('trafficmanager.cpp',),
    'received_flits_out': ('trafficmanager.cpp',),
    'sent_flits_out': ('trafficmanager.cpp',),
    'sent_packets_out': ('batchtrafficmanager.cpp',),
    'stats_out': ('trafficmanager.cpp',),
    'stored_flits_out': ('trafficmanager.cpp',),
    'tech_file': ('power/power_module.cpp',),
    'trace_file': ('tracetrafficmanager.cpp',),
    'trace_packet_log': ('tracetrafficmanager.cpp',),
    'use_noc_latency': ('networks/cmesh.cpp', 'networks/flatfly_onchip.cpp', 'networks/gec.cpp', 'networks/kncube.cpp'),
    'used_credits_out': ('trafficmanager.cpp',),
    'vct': ('routers/event_router.cpp',),
    'watch_file': ('trafficmanager.cpp',),
    'watch_flits': ('trafficmanager.cpp',),
    'watch_out': ('main.cpp',),
    'watch_packets': ('trafficmanager.cpp',),
    'wire_length': ('power/power_module.cpp',),
    'write_fraction': ('trafficmanager.cpp',),
    'write_reply_size': ('trafficmanager.cpp',),
    'write_request_size': ('trafficmanager.cpp',),
    'x': ('networks/cmesh.cpp', 'networks/flatfly_onchip.cpp'),
    'xr': ('networks/cmesh.cpp', 'networks/flatfly_onchip.cpp', 'traffic.cpp'),
    'y': ('networks/cmesh.cpp', 'networks/flatfly_onchip.cpp'),
    'yr': ('networks/cmesh.cpp', 'networks/flatfly_onchip.cpp'),
}



# ── scanning ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceRead:
    field: str
    locations: tuple[str, ...]


@dataclass(frozen=True)
class DriftReport:
    reads: tuple[SourceRead, ...]
    unregistered: tuple[str, ...]          # field not known at all
    uncovered_sites: tuple[str, ...]       # known gated field, new file
    stale_gated: tuple[str, ...]           # gate for a field no longer read
    stale_scope: tuple[str, ...]           # scope file no longer reads it
    stale_registered: tuple[str, ...]      # registry field no longer read

    @property
    def clean(self) -> bool:
        return not (self.unregistered or self.uncovered_sites
                    or self.stale_gated or self.stale_scope
                    or self.stale_registered)

    def raise_if_dirty(self) -> None:
        if self.clean:
            return
        parts = []
        if self.unregistered:
            parts.append(f"unregistered C++ config fields: "
                         f"{list(self.unregistered)}")
        if self.uncovered_sites:
            parts.append(f"read sites outside their gated scope: "
                         f"{list(self.uncovered_sites)}")
        if self.stale_gated:
            parts.append(f"gated fields no longer read: "
                         f"{list(self.stale_gated)}")
        if self.stale_scope:
            parts.append(f"scope entries no longer read: "
                         f"{list(self.stale_scope)}")
        if self.stale_registered:
            parts.append(f"registered fields no longer read: "
                         f"{list(self.stale_registered)}")
        raise SourceAuditError("; ".join(parts))


def scan_config_reads(source_root: Path) -> tuple[SourceRead, ...]:
    """Whole-file lexical scan of every .cpp/.hpp under source_root."""
    root = Path(source_root)
    found: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*")):
        if path.suffix not in (".cpp", ".hpp"):
            continue
        rel = str(path.relative_to(root))
        text = path.read_text(errors="ignore")
        for match in CONFIG_READ_RE.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            found.setdefault(match.group(CONFIG_READ_GROUP), []).append(
                f"{rel}:{line_no}")
    return tuple(SourceRead(field=name, locations=tuple(locs))
                 for name, locs in sorted(found.items()))


def audit_source_drift(
        source_root: Path,
        *,
        profile: Any = BOOKSIM_STANDALONE_PROFILE,
        gated: dict[str, tuple[str, ...]] = GATED_FIELDS,
        scope: dict[str, tuple[str, ...]] = GATED_SCOPE,
) -> DriftReport:
    reads = scan_config_reads(source_root)
    registry = set(profile.active_names()) | set(profile.inactive_names())
    unregistered: set[str] = set()
    uncovered: set[str] = set()
    discovered_gated: dict[str, set[str]] = {}
    for read in reads:
        files = {loc.split(":")[0] for loc in read.locations}
        discovered_gated.setdefault(read.field, set()).update(files)
        if read.field in registry:
            continue
        allowed = set(scope.get(read.field, ()))
        for path in sorted(files):
            if path not in allowed:
                uncovered.add(f"{read.field}@{path}")
    unregistered = {f for f in discovered_gated
                    if f not in gated and f not in registry}
    stale_scope = []
    for field, files in scope.items():
        actual = discovered_gated.get(field, set())
        for path in files:
            if path not in actual:
                stale_scope.append(f"{field}@{path}")
    read_fields = {r.field for r in reads}
    return DriftReport(
        reads=reads,
        unregistered=tuple(sorted(unregistered)),
        uncovered_sites=tuple(sorted(uncovered)),
        stale_gated=tuple(sorted(set(gated) - read_fields)),
        stale_scope=tuple(sorted(stale_scope)),
        stale_registered=tuple(sorted(registry - read_fields)))





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


__all__ = [
    "CONFIG_READ_RE",
    "GATED_FIELDS",
    "GATED_SCOPE",
    "MECHANISM_JUSTIFICATIONS",
    "DriftReport",
    "SourceAuditError",
    "SourceRead",
    "audit_source_drift",
    "parse_pin_gate",
    "scan_config_reads",
    "verify_gates",
]
