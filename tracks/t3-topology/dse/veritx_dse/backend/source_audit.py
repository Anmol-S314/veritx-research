"""veritx_dse.backend.source_audit — read-site source-drift guard
(B3.8a, hardened in B3.8e/B3.8f).

`booksim_profile.py` is the closed-world registry of configuration fields
the certified BookSim profile reads. This module keeps the closure closed
at READ-SITE granularity:

    whole-file lexical scan (multiline-safe) for
        config.Get*/config->Get*("field")
    -> for every discovered occurrence (field, file, line):
         * field is registered active in the profile registry, OR
         * the (field, file) site is declared in GATED_READ_SITES with
           the exact expected occurrence count (and, when recoverable, the
           enclosing method set), and its gate holds
    -> stale registry entries, stale gates, stale sites and uncovered or
       count-mismatched occurrences are refused.

The count check is what closes the same-file hole: adding a second
`config.GetInt("packet_size")` to trafficmanager.cpp fails even though
`packet_size@trafficmanager.cpp` was already gated once.

KNOWN BOUNDARY: this proves the DECLARED SET OF LEXICAL READ SITES has not
changed. It does not prove arbitrary C++ control-flow equivalence: moving
an existing read into a different branch while preserving the same lexical
identity and count is source modification, and producer/source identity in
B4 is the layer that detects it.

Scope note: this audits the STANDALONE certified fork
(third_party/booksim2/src). The embedded serving mirror is guarded by
read-site equivalence in tests; full embedded-source drift qualification
is deferred until SERVING_BOOKSIM2 receives an authoritative
ResolvedFabric bridge and becomes executable.
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

# Conservative class-method recovery for C++ definitions at column 0
# (e.g. `TrafficManager::TrafficManager(`). Free functions and unusual
# formatting fall back to (). Informational, and enforced only when the
# declared site records a non-empty function set.
ENCLOSING_DEF_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_:<>,~ \*&]*?\b([A-Za-z_]\w*::[A-Za-z_~]\w*)\s*\(")


class SourceAuditError(ValueError):
    """The certified source closure diverges from the audit registry."""


def enclosing_function(text: str, pos: int) -> tuple[str, ...]:
    current: tuple[str, ...] = ()
    for line in text[:pos].splitlines():
        m = ENCLOSING_DEF_RE.match(line)
        if m:
            current = (m.group(1),)
    return current


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


# ── gates (field level) ─────────────────────────────────

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


# ── declared read sites (field + file + count + functions) ──

@dataclass(frozen=True)
class GatedReadSite:
    path: str
    occurrences: int
    functions: tuple[str, ...] = ()

GATED_READ_SITES: dict[str, tuple[GatedReadSite, ...]] = {
    'Cd': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'Cd_pwr': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'Cg': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'Cg_pwr': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'Cgdl': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'Cw_cpl': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'Cw_gnd': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'H_DFQD1': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'H_INVD2': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'H_ND2D1': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'H_SRAM': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'IoffN': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'IoffP': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'IoffSRAM': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'LAMBDA': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'MetalPitch': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'R': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'Rw': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'Vdd': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'W_DFQD1': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'W_INVD2': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'W_ND2D1': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'W_SRAM': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'active_packets_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'batch_count': (GatedReadSite('batchtrafficmanager.cpp', 1, ()),),
    'batch_size': (GatedReadSite('batchtrafficmanager.cpp', 1, ()),),
    'burst_alpha': (GatedReadSite('injection.cpp', 1, ('InjectionProcess::New',)),),
    'burst_beta': (GatedReadSite('injection.cpp', 1, ('InjectionProcess::New',)),),
    'burst_r1': (GatedReadSite('injection.cpp', 1, ('InjectionProcess::New',)),),
    'c': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',)), GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',)), GatedReadSite('veritx_embed.cpp', 1, ('EmbedTM::PlatStats',))),
    'channel_sweep': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'channel_width': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'const_flits_per_packet': (GatedReadSite('routers/chaos_router.cpp', 1, ()),),
    'd': (GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',)),),
    'ejected_flits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'fail_seed': (GatedReadSite('networks/kncube.cpp', 2, ('KNCube::InsertRandomFaults',)),),
    'feedback_aging_scale': (GatedReadSite('buffer_state.cpp', 1, ('FeedbackSharedBufferPolicy::FeedbackSharedBufferPolicy',)),),
    'feedback_offset': (GatedReadSite('buffer_state.cpp', 1, ('FeedbackSharedBufferPolicy::FeedbackSharedBufferPolicy',)),),
    'free_credits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'hybrid': (GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',)),),
    'injected_flits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'k': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',)), GatedReadSite('networks/dragonfly.cpp', 1, ('DragonFlyNew::_ComputeSize',)), GatedReadSite('networks/fattree.cpp', 1, ('FatTree::_ComputeSize',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',)), GatedReadSite('networks/fly.cpp', 1, ('KNFly::_ComputeSize',)), GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',)), GatedReadSite('networks/kncube.cpp', 1, ('KNCube::_ComputeSize',)), GatedReadSite('networks/qtree.cpp', 1, ('QTree::_ComputeSize',)), GatedReadSite('networks/tree4.cpp', 1, ('Tree4::_ComputeSize',)), GatedReadSite('traffic.cpp', 2, ('TrafficPattern::New',)), GatedReadSite('veritx_embed.cpp', 1, ('EmbedTM::PlatStats',))),
    'max_credits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'max_held_slots': (GatedReadSite('buffer_state.cpp', 1, ('LimitedSharedBufferPolicy::LimitedSharedBufferPolicy',)),),
    'max_outstanding_requests': (GatedReadSite('batchtrafficmanager.cpp', 1, ()),),
    'mesh': (GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',)),),
    'multi_queue_size': (GatedReadSite('routers/chaos_router.cpp', 1, ()),),
    'n': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',)), GatedReadSite('networks/dragonfly.cpp', 1, ('DragonFlyNew::_ComputeSize',)), GatedReadSite('networks/fattree.cpp', 1, ('FatTree::_ComputeSize',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',)), GatedReadSite('networks/fly.cpp', 1, ('KNFly::_ComputeSize',)), GatedReadSite('networks/kncube.cpp', 1, ('KNCube::_ComputeSize',)), GatedReadSite('networks/qtree.cpp', 1, ('QTree::_ComputeSize',)), GatedReadSite('networks/tree4.cpp', 1, ('Tree4::_ComputeSize',)), GatedReadSite('traffic.cpp', 2, ('TrafficPattern::New',)), GatedReadSite('veritx_embed.cpp', 1, ('EmbedTM::PlatStats',))),
    'o': (GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',)),),
    'outstanding_credits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'packet_size': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',)),),
    'packet_size_rate': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',)),),
    'perm_seed': (GatedReadSite('traffic.cpp', 2, ('TrafficPattern::New',)),),
    'power_output_file': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'private_buf_end_vc': (GatedReadSite('buffer_state.cpp', 2, ('SharedBufferPolicy::SharedBufferPolicy',)),),
    'private_buf_size': (GatedReadSite('buffer_state.cpp', 2, ('SharedBufferPolicy::SharedBufferPolicy',)),),
    'private_buf_start_vc': (GatedReadSite('buffer_state.cpp', 2, ('SharedBufferPolicy::SharedBufferPolicy',)),),
    'private_bufs': (GatedReadSite('buffer_state.cpp', 1, ('SharedBufferPolicy::SharedBufferPolicy',)),),
    'read_reply_size': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',)),),
    'read_request_size': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',)),),
    'received_flits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'sent_flits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'sent_packets_out': (GatedReadSite('batchtrafficmanager.cpp', 1, ()),),
    'stats_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'stored_flits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'tech_file': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'trace_file': (GatedReadSite('tracetrafficmanager.cpp', 1, ()),),
    'trace_packet_log': (GatedReadSite('tracetrafficmanager.cpp', 1, ()),),
    'use_noc_latency': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_BuildNet',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_BuildNet',)), GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',)), GatedReadSite('networks/kncube.cpp', 1, ('KNCube::_BuildNet',))),
    'used_credits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'vct': (GatedReadSite('routers/event_router.cpp', 1, ()),),
    'watch_file': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'watch_flits': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'watch_out': (GatedReadSite('main.cpp', 1, ()),),
    'watch_packets': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',)),),
    'wire_length': (GatedReadSite('power/power_module.cpp', 1, ()),),
    'write_fraction': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',)),),
    'write_reply_size': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',)),),
    'write_request_size': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',)),),
    'x': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',))),
    'xr': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',)), GatedReadSite('traffic.cpp', 1, ('TrafficPattern::New',))),
    'y': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',))),
    'yr': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',))),
}



# ── scanning ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReadOccurrence:
    path: str
    line: int
    function: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceRead:
    field: str
    occurrences: tuple[ReadOccurrence, ...]

    @property
    def locations(self) -> tuple[str, ...]:
        return tuple(f"{o.path}:{o.line}" for o in self.occurrences)




@dataclass(frozen=True)
class DriftReport:
    reads: tuple[SourceRead, ...]
    unregistered: tuple[str, ...]          # field not known at all
    uncovered_sites: tuple[str, ...]       # new file, new count, new method
    stale_gated: tuple[str, ...]           # gate for a field no longer read
    stale_scope: tuple[str, ...]           # declared site no longer matches
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
            parts.append(f"read sites outside their declared site: "
                         f"{list(self.uncovered_sites)}")
        if self.stale_gated:
            parts.append(f"gated fields no longer read: "
                         f"{list(self.stale_gated)}")
        if self.stale_scope:
            parts.append(f"stale read-site declarations: "
                         f"{list(self.stale_scope)}")
        if self.stale_registered:
            parts.append(f"registered fields no longer read: "
                         f"{list(self.stale_registered)}")
        raise SourceAuditError("; ".join(parts))


def scan_config_reads(source_root: Path) -> tuple[SourceRead, ...]:
    """Whole-file lexical scan of every .cpp/.hpp under source_root."""
    root = Path(source_root)
    found: dict[str, list[ReadOccurrence]] = {}
    for path in sorted(root.rglob("*")):
        if path.suffix not in (".cpp", ".hpp"):
            continue
        rel = str(path.relative_to(root))
        text = path.read_text(errors="ignore")
        for match in CONFIG_READ_RE.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            found.setdefault(match.group(CONFIG_READ_GROUP), []).append(
                ReadOccurrence(path=rel, line=line_no,
                               function=enclosing_function(text,
                                                           match.start())))
    return tuple(SourceRead(field=name, occurrences=tuple(occ))
                 for name, occ in sorted(found.items()))


def _site_key(field: str, path: str) -> str:
    return f"{field}@{path}"


def audit_source_drift(
        source_root: Path,
        *,
        profile: Any = BOOKSIM_STANDALONE_PROFILE,
        gated: dict[str, tuple[str, ...]] = GATED_FIELDS,
        sites: dict[str, tuple[GatedReadSite, ...]] = GATED_READ_SITES,
) -> DriftReport:
    reads = scan_config_reads(source_root)
    registry = set(profile.active_names()) | set(profile.inactive_names())
    by_field_file: dict[tuple[str, str], list[ReadOccurrence]] = {}
    for read in reads:
        for occ in read.occurrences:
            by_field_file.setdefault((read.field, occ.path), []).append(occ)

    uncovered: list[str] = []
    unregistered: set[str] = set()
    matched: set[str] = set()
    for (field, path), occs in sorted(by_field_file.items()):
        if field in registry:
            matched.add(_site_key(field, path))
            continue
        declared = {s.path: s for s in sites.get(field, ())}
        if field not in gated:
            unregistered.add(field)
            continue
        site = declared.get(path)
        key = _site_key(field, path)
        if site is None:
            uncovered.append(
                f"{key}: {len(occs)} occurrence(s) not declared")
            continue
        if len(occs) != site.occurrences:
            uncovered.append(
                f"{key}: {len(occs)} occurrence(s), declared "
                f"{site.occurrences}")
            continue
        if site.functions:
            observed = {f for occ in occs for f in occ.function}
            if observed != set(site.functions):
                uncovered.append(
                    f"{key}: functions {sorted(observed)} != declared "
                    f"{sorted(site.functions)}")
                continue
        matched.add(key)

    stale_scope: list[str] = []
    for field, declared_sites in sites.items():
        for site in declared_sites:
            key = _site_key(field, site.path)
            if key not in matched:
                stale_scope.append(key)

    read_fields = {r.field for r in reads}
    return DriftReport(
        reads=reads,
        unregistered=tuple(sorted(unregistered)),
        uncovered_sites=tuple(sorted(uncovered)),
        stale_gated=tuple(sorted(set(gated) - read_fields)),
        stale_scope=tuple(sorted(stale_scope)),
        stale_registered=tuple(sorted(registry - read_fields)))


def read_accounting(
        source_root: Path,
        *,
        profile: Any = BOOKSIM_STANDALONE_PROFILE,
        gated: dict[str, tuple[str, ...]] = GATED_FIELDS,
) -> dict[str, int]:
    """Occurrence-level accounting for reports (not a pass/fail gate)."""
    reads = scan_config_reads(source_root)
    active = set(profile.active_names())
    inactive = set(profile.inactive_names())
    total = gated_occ = active_occ = inactive_occ = 0
    for read in reads:
        n = len(read.occurrences)
        total += n
        if read.field in active:
            active_occ += n
        elif read.field in inactive:
            inactive_occ += n
        elif read.field in gated:
            gated_occ += n
    return {
        "unique_fields": len(reads),
        "total_occurrences": total,
        "registered_active_occurrences": active_occ,
        "registered_inactive_occurrences": inactive_occ,
        "gated_occurrences": gated_occ,
    }





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


def verify_site_gates(rendered_values: dict[str, str]) -> None:
    """Every declared site's gate must hold for the rendered config."""
    for field, gates in GATED_FIELDS.items():
        for gate in gates:
            pin = parse_pin_gate(gate)
            if pin is None:
                continue
            name, value = pin
            if name not in rendered_values:
                raise SourceAuditError(
                    f"site gate for {field!r} names unpinned field "
                    f"{name!r}")
            if rendered_values[name] != value:
                raise SourceAuditError(
                    f"site gate {gate!r} for {field!r} does not hold: "
                    f"rendered {name}={rendered_values[name]!r}")


__all__ = [
    "CONFIG_READ_RE",
    "GATED_FIELDS",
    "GATED_READ_SITES",
    "MECHANISM_JUSTIFICATIONS",
    "DriftReport",
    "GatedReadSite",
    "ReadOccurrence",
    "SourceAuditError",
    "SourceRead",
    "audit_source_drift",
    "enclosing_function",
    "parse_pin_gate",
    "read_accounting",
    "scan_config_reads",
    "verify_gates",
    "verify_site_gates",
]
