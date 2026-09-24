"""veritx_dse.backend.source_audit — vendored-BookSim config read audit.

BookSim's certified projection claims that specific configuration fields
affect execution. This module proves it against the ACTUAL vendored
source instead of trusting a hand-written table:

    scan_config_reads(source_root)  -> every field the fork reads
    audit_profile_reads(profile, source_root) -> drift report / refusal

The read pattern is the fork's accessor convention
(``cfg->GetInt("k")`` / ``.GetStr("topology")`` / ``GetFloat(...)``),
revalidated here against ``third_party/booksim2/src``. Stale
line-number tables are deliberately NOT copied: a field is revalidated by
name against the current tree, so a fork upgrade that drops a read fails
closed rather than silently passing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SOURCE_EXTENSIONS = (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h", ".ipp")

#: receiver name is irrelevant, so aliases cannot evade the scan
CONFIG_READ_RE = re.compile(
    r"\b[A-Za-z_]\w*\s*(?:->|\.)\s*Get"
    r"(?:Int|Str|Float|IntArray|StrArray|FloatArray)"
    r"\s*\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"")

#: the parser accepts a BARE string as well (`GetStr("x")` with an alias
#: receiver is covered above; this catches free-function style helpers)
CONFIG_READ_FREE_RE = re.compile(
    r"\bGet(?:Int|Str|Float|IntArray|StrArray|FloatArray)"
    r"\s*\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"")


class SourceAuditError(ValueError):
    """The certified profile diverges from the vendored source."""


@dataclass(frozen=True)
class ReadOccurrence:
    field: str
    path: str


@dataclass(frozen=True)
class DriftReport:
    """Declared/observed field accounting for one profile."""

    declared: tuple[str, ...]
    observed: tuple[str, ...]
    missing_from_source: tuple[str, ...]
    undeclared_in_profile: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.missing_from_source


def scan_config_reads(source_root: str | Path) -> tuple[ReadOccurrence, ...]:
    """Every config field the vendored BookSim tree actually reads."""
    root = Path(source_root)
    if not root.is_dir():
        raise SourceAuditError(f"BookSim source root not found: {root}")
    found: list[ReadOccurrence] = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in SOURCE_EXTENSIONS or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = str(path.relative_to(root))
        for regex in (CONFIG_READ_RE, CONFIG_READ_FREE_RE):
            for match in regex.finditer(text):
                found.append(ReadOccurrence(match.group(1), rel))
    # de-duplicate (a field read by several files is one field)
    seen: set[tuple[str, str]] = set()
    unique: list[ReadOccurrence] = []
    for row in found:
        key = (row.field, row.path)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return tuple(unique)


def observed_fields(source_root: str | Path) -> frozenset[str]:
    return frozenset(row.field for row in scan_config_reads(source_root))


def audit_profile_reads(profile: object, source_root: str | Path, *,
                        strict: bool = True) -> DriftReport:
    """Revalidate a profile's emitted fields against the vendored source.

    ``strict`` refuses when a field the profile EMITS is not read by the
    fork at all: that is the drift that silently voids a certified
    projection. Fields the fork reads but the profile does not declare
    are reported (they are gated/inactive by construction) and are not
    fatal unless ``strict`` and the field is in the profile's rendered
    set.
    """
    observed = observed_fields(source_root)
    declared = tuple(sorted(profile.rendered_names()))
    missing = tuple(name for name in declared if name not in observed)
    undeclared = tuple(sorted(observed - set(profile.known_names())))
    report = DriftReport(declared=declared, observed=tuple(sorted(observed)),
                         missing_from_source=missing,
                         undeclared_in_profile=undeclared)
    if strict and missing:
        raise SourceAuditError(
            "source drift: the profile emits configuration field(s) the "
            f"vendored BookSim never reads: {list(missing)}; the certified "
            "projection would be void")
    return report




# ── site-gated read closure (reclaimed verbatim from the RT candidate
# 26e6f9dc, additive only): the RT backend stack (backend/booksim.py,
# backend/meshdor.py, backend/meshdor_profile.py) authenticates rendered
# configs against these declared read sites. The canonical simple audit
# API above is untouched; this block adds names only.
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

__all__ = [
    "CONFIG_READ_FREE_RE", "CONFIG_READ_RE", "DriftReport", "ReadOccurrence",
    "SOURCE_EXTENSIONS", "SourceAuditError", "audit_profile_reads",
    "observed_fields", "scan_config_reads",
    "GATED_FIELDS", "GATED_READ_SITES", "GatedReadSite",
    "MECHANISM_JUSTIFICATIONS", "parse_pin_gate", "verify_gates",
    "verify_site_gates",
]
