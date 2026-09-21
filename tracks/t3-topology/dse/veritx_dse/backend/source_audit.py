"""veritx_dse.backend.source_audit — site-gated source-drift guard
(B3.8a, hardened through B3.8g).

`booksim_profile.py` is the closed-world registry of configuration fields
the certified BookSim profile reads. This module keeps the closure closed
at READ-SITE granularity with an explicit, site-specific gate:

    conservative whole-file lexical scan for any receiver
        <receiver>.Get*(...) / <receiver>->Get*(...)
    over .cpp .cc .cxx .hpp .hh .h .ipp
    -> for every discovered (field, file, occurrence):
         * ACTIVE registered field            -> accepted as registered
         * INACTIVE_FOR_PROFILE field         -> MUST match a declared
                                                 GATED_READ_SITES entry
                                                 (file, count, methods,
                                                 site gates)
         * unregistered field with a declared site -> same site checks
         * otherwise                          -> refused
    -> stale registry entries, stale gates, stale sites and uncovered
       occurrences are refused.

INACTIVE_FOR_PROFILE is documentation/accounting, not proof: those fields
are exactly the ones whose safety depends on a gate, so they are subjected
to the same site checks as unregistered gated fields.

KNOWN BOUNDARY: this proves the DECLARED SET OF LEXICAL READ SITES and
each site's explicit disabling mechanism have not changed. It does not
prove arbitrary C++ control-flow equivalence when an existing read is
moved or semantically repurposed without changing its lexical identity;
B4 producer/source identity detects such source modification. B4 proves
producer identity, not semantic equivalence.

Scope note: this audits the STANDALONE certified fork
(third_party/booksim2/src). The embedded serving mirror is guarded by a
read-site comparison (field, file, occurrence count, recovered methods)
in tests; full embedded-source equivalence and execution qualification
remain deferred until SERVING_BOOKSIM2 has an authoritative ResolvedFabric
bridge.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .booksim_profile import BOOKSIM_STANDALONE_PROFILE, ConfigRead

# Conservative: receiver name is irrelevant, so aliases cannot evade.
CONFIG_READ_RE = re.compile(
    r"\b[A-Za-z_]\w*\s*(?:->|\.)\s*Get"
    r"(?:Int|Str|Float|IntArray|StrArray|FloatArray)"
    r"\s*\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"")
CONFIG_READ_GROUP = 1
SOURCE_EXTENSIONS: tuple[str, ...] = (
    ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h", ".ipp")

# Class-method recovery for C++ definitions at column 0. Informational;
# enforced only when a declared site records a non-empty function set.
ENCLOSING_DEF_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_:<>,~ \*&]*?\b([A-Za-z_]\w*::[A-Za-z_~]\w*)\s*\(")


class SourceAuditError(ValueError):
    """The certified source closure diverges from the audit registry."""


@dataclass(frozen=True)
class GatedReadSite:
    """One declared gated read site: file, count, methods, and ITS gates.

    ``gates`` is site-specific: a site must not inherit a gate that
    justifies a different site of the same field.
    """

    path: str
    occurrences: int
    functions: tuple[str, ...] = ()
    gates: tuple[str, ...] = ()


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
        "read only when config.GetIntMap().count(field) (veritx_embed.cpp); "
        "the certified projector never emits k/n/c"),
    "topology_dispatch": (
        "read only inside a network class that Network::New never "
        "constructs for this profile (topology dispatch in "
        "networks/network.cpp); the certified mesh profile constructs "
        "KNCube only, so no other network class is instantiated"),
}


# ── declared read sites (field + file + count + methods + gates) ──

GATED_READ_SITES: dict[str, tuple[GatedReadSite, ...]] = {
    'Cd': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'Cd_pwr': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'Cg': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'Cg_pwr': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'Cgdl': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'Cw_cpl': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'Cw_gnd': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'H_DFQD1': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'H_INVD2': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'H_ND2D1': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'H_SRAM': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'IoffN': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'IoffP': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'IoffSRAM': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'LAMBDA': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'MetalPitch': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'R': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'Rw': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'Vdd': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'W_DFQD1': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'W_INVD2': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'W_ND2D1': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'W_SRAM': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'active_packets_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'batch_count': (GatedReadSite('batchtrafficmanager.cpp', 1, (), ('pin:sim_type=latency',)),),
    'batch_size': (GatedReadSite('batchtrafficmanager.cpp', 1, (), ('pin:sim_type=latency',)),),
    'burst_alpha': (GatedReadSite('injection.cpp', 1, ('InjectionProcess::New',), ('pin:injection_process=bernoulli',)),),
    'burst_beta': (GatedReadSite('injection.cpp', 1, ('InjectionProcess::New',), ('pin:injection_process=bernoulli',)),),
    'burst_r1': (GatedReadSite('injection.cpp', 1, ('InjectionProcess::New',), ('pin:injection_process=bernoulli',)),),
    'c': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('veritx_embed.cpp', 1, ('EmbedTM::PlatStats',), ('conditional_presence',))),
    'channel_sweep': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'channel_width': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'const_flits_per_packet': (GatedReadSite('routers/chaos_router.cpp', 1, (), ('pin:router=iq',)),),
    'd': (GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',), ('pin:topology=anynet',)),),
    'ejected_flits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'fail_seed': (GatedReadSite('networks/kncube.cpp', 2, ('KNCube::InsertRandomFaults',), ('pin:topology=anynet',)),),
    'feedback_aging_scale': (GatedReadSite('buffer_state.cpp', 1, ('FeedbackSharedBufferPolicy::FeedbackSharedBufferPolicy',), ('pin:buffer_policy=private',)),),
    'feedback_offset': (GatedReadSite('buffer_state.cpp', 1, ('FeedbackSharedBufferPolicy::FeedbackSharedBufferPolicy',), ('pin:buffer_policy=private',)),),
    'free_credits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'hybrid': (GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',), ('pin:topology=anynet',)),),
    'injected_flits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'k': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/dragonfly.cpp', 1, ('DragonFlyNew::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/fattree.cpp', 1, ('FatTree::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/fly.cpp', 1, ('KNFly::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/kncube.cpp', 1, ('KNCube::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/qtree.cpp', 1, ('QTree::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/tree4.cpp', 1, ('Tree4::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('traffic.cpp', 2, ('TrafficPattern::New',), ('pattern_dispatch',)), GatedReadSite('veritx_embed.cpp', 1, ('EmbedTM::PlatStats',), ('conditional_presence',))),
    'max_credits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'max_held_slots': (GatedReadSite('buffer_state.cpp', 1, ('LimitedSharedBufferPolicy::LimitedSharedBufferPolicy',), ('pin:buffer_policy=private',)),),
    'max_outstanding_requests': (GatedReadSite('batchtrafficmanager.cpp', 1, (), ('pin:sim_type=latency',)),),
    'mesh': (GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',), ('pin:topology=anynet',)),),
    'multi_queue_size': (GatedReadSite('routers/chaos_router.cpp', 1, (), ('pin:router=iq',)),),
    'n': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/dragonfly.cpp', 1, ('DragonFlyNew::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/fattree.cpp', 1, ('FatTree::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/fly.cpp', 1, ('KNFly::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/kncube.cpp', 1, ('KNCube::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/qtree.cpp', 1, ('QTree::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/tree4.cpp', 1, ('Tree4::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('traffic.cpp', 2, ('TrafficPattern::New',), ('pattern_dispatch',)), GatedReadSite('veritx_embed.cpp', 1, ('EmbedTM::PlatStats',), ('conditional_presence',))),
    'o': (GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',), ('pin:topology=anynet',)),),
    'outstanding_credits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'packet_size': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',), ('trace_records',)),),
    'packet_size_rate': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',), ('trace_records',)),),
    'perm_seed': (GatedReadSite('traffic.cpp', 2, ('TrafficPattern::New',), ('pattern_dispatch',)),),
    'power_output_file': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'private_buf_end_vc': (GatedReadSite('buffer_state.cpp', 2, ('SharedBufferPolicy::SharedBufferPolicy',), ('pin:buffer_policy=private',)),),
    'private_buf_size': (GatedReadSite('buffer_state.cpp', 2, ('SharedBufferPolicy::SharedBufferPolicy',), ('pin:buffer_policy=private',)),),
    'private_buf_start_vc': (GatedReadSite('buffer_state.cpp', 2, ('SharedBufferPolicy::SharedBufferPolicy',), ('pin:buffer_policy=private',)),),
    'private_bufs': (GatedReadSite('buffer_state.cpp', 1, ('SharedBufferPolicy::SharedBufferPolicy',), ('pin:buffer_policy=private',)),),
    'read_reply_size': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',), ('pin:use_read_write=0',)),),
    'read_request_size': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',), ('pin:use_read_write=0',)),),
    'received_flits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'sent_flits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'sent_packets_out': (GatedReadSite('batchtrafficmanager.cpp', 1, (), ('pin:sim_type=latency',)),),
    'stats_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'stored_flits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'tech_file': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'trace_file': (GatedReadSite('tracetrafficmanager.cpp', 1, (), ('pin:sim_type=latency',)),),
    'trace_packet_log': (GatedReadSite('tracetrafficmanager.cpp', 1, (), ('pin:sim_type=latency',)),),
    'use_noc_latency': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_BuildNet',), ('pin:topology=anynet',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_BuildNet',), ('pin:topology=anynet',)), GatedReadSite('networks/gec.cpp', 1, ('GEC::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/kncube.cpp', 1, ('KNCube::_BuildNet',), ('pin:topology=anynet',))),
    'used_credits_out': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'vct': (GatedReadSite('routers/event_router.cpp', 1, (), ('pin:router=iq',)),),
    'watch_file': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'watch_flits': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'watch_out': (GatedReadSite('main.cpp', 1, (), ('diagnostic_only',)),),
    'watch_packets': (GatedReadSite('trafficmanager.cpp', 1, ('TrafficManager::New',), ('diagnostic_only',)),),
    'wire_length': (GatedReadSite('power/power_module.cpp', 1, (), ('pin:sim_power=0',)),),
    'write_fraction': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',), ('pin:use_read_write=0',)),),
    'write_reply_size': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',), ('pin:use_read_write=0',)),),
    'write_request_size': (GatedReadSite('trafficmanager.cpp', 2, ('TrafficManager::New',), ('pin:use_read_write=0',)),),
    'x': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',), ('pin:topology=anynet',))),
    'xr': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('traffic.cpp', 1, ('TrafficPattern::New',), ('pattern_dispatch',))),
    'y': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',), ('pin:topology=anynet',))),
    'yr': (GatedReadSite('networks/cmesh.cpp', 1, ('CMesh::_ComputeSize',), ('pin:topology=anynet',)), GatedReadSite('networks/flatfly_onchip.cpp', 1, ('FlatFlyOnChip::_ComputeSize',), ('pin:topology=anynet',))),
}


GATED_FIELDS: dict[str, tuple[str, ...]] = {
    field: tuple(sorted({g for site in sites for g in site.gates}))
    for field, sites in GATED_READ_SITES.items()
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
    unregistered: tuple[str, ...]
    uncovered_sites: tuple[str, ...]
    stale_gated: tuple[str, ...]
    stale_scope: tuple[str, ...]
    stale_registered: tuple[str, ...]

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


def enclosing_function(text: str, pos: int) -> tuple[str, ...]:
    current: tuple[str, ...] = ()
    for line in text[:pos].splitlines():
        m = ENCLOSING_DEF_RE.match(line)
        if m:
            current = (m.group(1),)
    return current


def scan_config_reads(source_root: Path) -> tuple[SourceRead, ...]:
    """Conservative whole-file lexical scan of all supported extensions."""
    root = Path(source_root)
    found: dict[str, list[ReadOccurrence]] = {}
    for path in sorted(root.rglob("*")):
        if path.suffix not in SOURCE_EXTENSIONS:
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
        sites: dict[str, tuple[GatedReadSite, ...]] = GATED_READ_SITES,
) -> DriftReport:
    """Enforce per-site evidence for every non-active read.

    ACTIVE fields are accepted on registry membership. INACTIVE_FOR_PROFILE
    and unregistered-gated fields BOTH require a matching declared site.
    """
    reads = scan_config_reads(source_root)
    active = set(profile.active_names())
    inactive = set(profile.inactive_names())
    by_field_file: dict[tuple[str, str], list[ReadOccurrence]] = {}
    for read in reads:
        for occ in read.occurrences:
            by_field_file.setdefault((read.field, occ.path), []).append(occ)

    uncovered: list[str] = []
    unregistered: set[str] = set()
    matched: set[str] = set()
    for (field, path), occs in sorted(by_field_file.items()):
        key = _site_key(field, path)
        if field in active:
            matched.add(key)
            continue
        declared = {s.path: s for s in sites.get(field, ())}
        if field not in inactive and field not in sites:
            unregistered.add(field)
            continue
        site = declared.get(path)
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
        if not site.gates:
            uncovered.append(f"{key}: site has no explicit gate")
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
        stale_gated=tuple(sorted(set(sites) - read_fields)),
        stale_scope=tuple(sorted(stale_scope)),
        stale_registered=tuple(sorted(
            (active | inactive) - read_fields)))


def read_accounting(
        source_root: Path,
        *,
        profile: Any = BOOKSIM_STANDALONE_PROFILE,
) -> dict[str, int]:
    """Occurrence-level accounting for reports."""
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
        else:
            gated_occ += n
    return {
        "unique_fields": len(reads),
        "total_occurrences": total,
        "registered_active_occurrences": active_occ,
        "registered_inactive_occurrences": inactive_occ,
        "unregistered_gated_occurrences": gated_occ,
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


def verify_site_gates(
        sites: dict[str, tuple[GatedReadSite, ...]],
        rendered_values: dict[str, str]) -> None:
    """Every declared SITE gate must hold for the rendered certified config."""
    for field, declared_sites in sites.items():
        for site in declared_sites:
            if not site.gates:
                raise SourceAuditError(
                    f"site {field}@{site.path} has no explicit gate")
            for gate in site.gates:
                pin = parse_pin_gate(gate)
                if pin is not None:
                    name, value = pin
                    if name not in rendered_values:
                        raise SourceAuditError(
                            f"site {field}@{site.path} gate names unpinned "
                            f"field {name!r}")
                    if rendered_values[name] != value:
                        raise SourceAuditError(
                            f"site gate {gate!r} for {field}@{site.path} "
                            f"does not hold: rendered "
                            f"{name}={rendered_values[name]!r}")
                elif gate not in MECHANISM_JUSTIFICATIONS:
                    raise SourceAuditError(
                        f"site {field}@{site.path} uses unknown gate "
                        f"mechanism {gate!r}")


def verify_gates(rendered_values: dict[str, str]) -> None:
    verify_site_gates(GATED_READ_SITES, rendered_values)


# ── per-profile read sites (P1B-Q1) ────────────────────────────────────
# Network::New constructs KNCube and nothing else for topology=mesh, so
# every read inside another network class is unreachable by dispatch.
# The mesh profile therefore re-gates those sites on the dispatch
# mechanism instead of a pin the mesh config cannot satisfy. KNCube's
# own fail_seed read is gated by link_failures=0 (pinned in the profile).

_MESH_OTHER_NETWORK_FILES = frozenset({
    "networks/anynet.cpp", "networks/cmesh.cpp", "networks/fly.cpp",
    "networks/fattree.cpp", "networks/qtree.cpp", "networks/tree4.cpp",
    "networks/flatfly_onchip.cpp", "networks/dragonfly.cpp",
    "networks/gec.cpp",
})

# Extra declarations that only the mesh profile needs: fields inactive
# for mesh whose reads live in files that are dispatch-unreachable.
_MESH_EXTRA_SITES: dict[str, tuple[GatedReadSite, ...]] = {
    "network_file": (
        GatedReadSite("networks/anynet.cpp", 1,
                      ("AnyNet::_ComputeSize",), ("topology_dispatch",)),
    ),
}


def mesh_gated_read_sites() -> dict[str, tuple[GatedReadSite, ...]]:
    """GATED_READ_SITES re-gated for the certified native-mesh profile."""
    out: dict[str, tuple[GatedReadSite, ...]] = {}
    for field, sites in GATED_READ_SITES.items():
        rows = []
        for site in sites:
            gates = site.gates
            if site.path in _MESH_OTHER_NETWORK_FILES:
                gates = tuple("topology_dispatch" for _ in site.gates)
            elif site.path == "networks/kncube.cpp":
                # KNCube IS constructed for topology=mesh; its reads are
                # either active fields (k, n, use_noc_latency) or gated by
                # fail_seed's own switch.
                gates = ("pin:link_failures=0",) if field == "fail_seed" \
                    else ("pin:topology=mesh",)
            rows.append(GatedReadSite(site.path, site.occurrences,
                                      site.functions, gates))
        out[field] = tuple(rows)
    for field, sites in _MESH_EXTRA_SITES.items():
        out[field] = out.get(field, ()) + sites
    return out


MESH_GATED_READ_SITES = mesh_gated_read_sites()


__all__ = [
    "CONFIG_READ_RE",
    "GATED_FIELDS",
    "GATED_READ_SITES",
    "MECHANISM_JUSTIFICATIONS",
    "SOURCE_EXTENSIONS",
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
