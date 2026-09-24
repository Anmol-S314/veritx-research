"""veritx_dse.backend.booksim_profile — closed-world BookSim config audit (B3.7g).

Every configuration field the certified BookSim execution path can read
must appear here exactly once, with:

    * the owner class of its value (ParameterOwner), and
    * the source location(s) that read it, and
    * for BACKEND_PROFILE-owned fields, the explicit pinned value.

The invariant this table exists to enforce:

    No result-affecting value consumed by the certified backend may come
    from an unnamed, unversioned compiled default.

INACTIVE_FOR_PROFILE entries are fields the code reads but which cannot
affect the certified profile's result because a gating field is pinned
(e.g. `speculative=0` gates the spec_* fields; `buffer_policy=private`
makes the shared-buffer knobs dead). Each inactive entry states that
gating argument; it is documented, not hidden.

Source locations were extracted from the vendored fork at
`third_party/booksim2/src` at the B3.7g commit. The audit is intentionally
explicit-data: adding a new read without registering it fails the
closed-world test in `tests/test_backend_contracts.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import ParameterOwner

BOOKSIM_CERTIFIED_PROFILE_ID = "CERTIFIED_BOOKSIM_ANYNET_V1"
BOOKSIM_CERTIFIED_SEMANTICS_VERSION = "booksim2-fork+B3.7b-anynet-dump"


@dataclass(frozen=True)
class ConfigRead:
    """One configuration field read on the certified execution path."""

    name: str
    owner: ParameterOwner
    source: str
    pin: Any = None
    note: str = ""

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("ConfigRead.name must be a non-empty string")
        if not isinstance(self.source, str) or not self.source:
            raise ValueError(
                f"ConfigRead {self.name!r} must record its source location")
        if self.owner is ParameterOwner.INACTIVE_FOR_PROFILE:
            if self.pin is not None:
                raise ValueError(
                    f"inactive profile field {self.name!r} must not pin a "
                    "value (it is documented, not emitted)")
            if not self.note:
                raise ValueError(
                    f"inactive profile field {self.name!r} must state why "
                    "it cannot affect the certified profile")
        elif self.owner is ParameterOwner.BACKEND_PROFILE:
            if self.pin is None and self.name != "traffic" and \
                    self.name != "sample_period":
                raise ValueError(
                    f"BACKEND_PROFILE field {self.name!r} must carry an "
                    "explicit pinned value")


A = ParameterOwner

# ── the audit ───────────────────────────────────────────────────────────
# Grouped by the file that reads the field; a field read by several files
# lists every location.

BOOKSIM_CERTIFIED_CONFIG_AUDIT: tuple[ConfigRead, ...] = (
    # standalone driver (main.cpp)
    ConfigRead("print_activity", A.BACKEND_PROFILE, "main.cpp:170", 0),
    ConfigRead("viewer_trace", A.BACKEND_PROFILE, "main.cpp:171", 0),
    ConfigRead("sim_power", A.BACKEND_PROFILE, "main.cpp:139", 0,
               note="power model disabled"),
    ConfigRead("watch_out", A.INACTIVE_FOR_PROFILE, "main.cpp:173",
               note="no watch output is requested; empty default"),

    # network construction
    ConfigRead("topology", A.BACKEND_PROFILE, "networks/network.cpp:89",
               "anynet", note="certified projector renders AnyNet"),
    ConfigRead("link_failures", A.BACKEND_PROFILE, "networks/network.cpp:131",
               0),
    ConfigRead("network_file", A.FABRIC_DERIVED, "networks/anynet.cpp:81",
               note="rendered logical name topology.anynet"),
    ConfigRead("routing_dump_file", A.EXECUTION_POLICY,
               "networks/anynet.cpp:83",
               note="executed-route evidence path (standalone only)"),
    ConfigRead("classes", A.BACKEND_PROFILE,
               "routers/router.cpp:71; trafficmanager.cpp:130; "
               "buffer.cpp:54; buffer_state.cpp:561; power/power_module.cpp:44",
               1, note="single-class trace execution"),

    # router base (routers/router.cpp)
    ConfigRead("router", A.BACKEND_PROFILE, "routers/router.cpp:161", "iq"),
    ConfigRead("st_prepare_delay", A.FABRIC_DERIVED, "routers/router.cpp:65"),
    ConfigRead("st_final_delay", A.FABRIC_DERIVED, "routers/router.cpp:66"),
    ConfigRead("credit_delay", A.FABRIC_DERIVED, "routers/router.cpp:67"),
    ConfigRead("input_speedup", A.FABRIC_DERIVED, "routers/router.cpp:68"),
    ConfigRead("output_speedup", A.FABRIC_DERIVED, "routers/router.cpp:69"),
    ConfigRead("internal_speedup", A.FABRIC_DERIVED, "routers/router.cpp:70"),

    # VC objects (vc.cpp)
    ConfigRead("priority", A.BACKEND_PROFILE, "vc.cpp:57; "
               "trafficmanager.cpp:89", "none",
               note="no priority scheme; class_priority is dead"),
    ConfigRead("vc_priority_donation", A.BACKEND_PROFILE, "vc.cpp:70", 0),

    # IQ router (routers/iq_router.cpp)
    ConfigRead("num_vcs", A.FABRIC_DERIVED,
               "routers/iq_router.cpp:55; trafficmanager.cpp:78; "
               "buffer.cpp:38; buffer_state.cpp:89,127,267,371,542; "
               "routefunc.cpp:1920; power/power_module.cpp:48"),
    ConfigRead("vc_busy_when_full", A.BACKEND_PROFILE,
               "routers/iq_router.cpp:57", 0),
    ConfigRead("vc_prioritize_empty", A.BACKEND_PROFILE,
               "routers/iq_router.cpp:58", 0),
    ConfigRead("vc_shuffle_requests", A.BACKEND_PROFILE,
               "routers/iq_router.cpp:59", 0),
    ConfigRead("speculative", A.BACKEND_PROFILE,
               "routers/iq_router.cpp:61", 0,
               note="gates spec_check_*/spec_sw_allocator"),
    ConfigRead("spec_check_elig", A.BACKEND_PROFILE,
               "routers/iq_router.cpp:62", 0,
               note="gated by speculative=0; pinned to prevent future "
                    "compiled-default drift"),
    ConfigRead("spec_check_cred", A.BACKEND_PROFILE,
               "routers/iq_router.cpp:63", 0,
               note="gated by speculative=0"),
    ConfigRead("spec_mask_by_reqs", A.BACKEND_PROFILE,
               "routers/iq_router.cpp:64", 0,
               note="gated by speculative=0"),
    ConfigRead("routing_delay", A.FABRIC_DERIVED,
               "routers/iq_router.cpp:66; vc.cpp:54; trafficmanager.cpp:273"),
    ConfigRead("vc_alloc_delay", A.FABRIC_DERIVED,
               "routers/iq_router.cpp:67; trafficmanager.cpp:271"),
    ConfigRead("sw_alloc_delay", A.FABRIC_DERIVED,
               "routers/iq_router.cpp:71; trafficmanager.cpp:272"),
    ConfigRead("routing_function", A.FABRIC_DERIVED,
               "routers/iq_router.cpp:77; trafficmanager.cpp:113"),
    ConfigRead("vc_allocator", A.FABRIC_DERIVED, "routers/iq_router.cpp:100"),
    ConfigRead("sw_allocator", A.FABRIC_DERIVED, "routers/iq_router.cpp:118"),
    ConfigRead("spec_sw_allocator", A.BACKEND_PROFILE,
               "routers/iq_router.cpp:128", "prio",
               note="gated by speculative=0"),
    ConfigRead("noq", A.BACKEND_PROFILE,
               "routers/iq_router.cpp:145; trafficmanager.cpp:121", 0),
    ConfigRead("output_buffer_size", A.FABRIC_DERIVED,
               "routers/iq_router.cpp:159"),
    ConfigRead("hold_switch_for_packet", A.FABRIC_DERIVED,
               "routers/iq_router.cpp:164; trafficmanager.cpp:312"),
    ConfigRead("arb_type", A.BACKEND_PROFILE,
               "allocators/allocator.cpp:465,469", "round_robin"),
    ConfigRead("alloc_iters", A.FABRIC_DERIVED,
               "allocators/allocator.cpp:450,453,462"),

    # buffer state / buffers
    ConfigRead("buffer_policy", A.FABRIC_DERIVED, "buffer_state.cpp:65"),
    ConfigRead("buf_size", A.BACKEND_PROFILE, "buffer_state.cpp:90; "
               "buffer.cpp:40", -1,
               note="must be <=0 so PrivateBufferPolicy uses vc_buf_size"),
    ConfigRead("vc_buf_size", A.FABRIC_DERIVED,
               "buffer_state.cpp:92; buffer.cpp:42; power/power_module.cpp:49"),
    ConfigRead("wait_for_tail_credit", A.FABRIC_DERIVED,
               "buffer_state.cpp:550"),
    ConfigRead("private_bufs", A.INACTIVE_FOR_PROFILE,
               "buffer_state.cpp:128",
               note="SharedBufferPolicy only; buffer_policy=private pinned"),
    ConfigRead("private_buf_size", A.INACTIVE_FOR_PROFILE,
               "buffer_state.cpp:142,144",
               note="SharedBufferPolicy only; buffer_policy=private pinned"),
    ConfigRead("private_buf_start_vc", A.INACTIVE_FOR_PROFILE,
               "buffer_state.cpp:153,155",
               note="SharedBufferPolicy only; buffer_policy=private pinned"),
    ConfigRead("private_buf_end_vc", A.INACTIVE_FOR_PROFILE,
               "buffer_state.cpp:166,168",
               note="SharedBufferPolicy only; buffer_policy=private pinned"),
    ConfigRead("max_held_slots", A.INACTIVE_FOR_PROFILE,
               "buffer_state.cpp:268",
               note="LimitedSharedBufferPolicy only; buffer_policy=private "
                    "pinned"),
    ConfigRead("feedback_aging_scale", A.INACTIVE_FOR_PROFILE,
               "buffer_state.cpp:369",
               note="FeedbackSharedBufferPolicy only"),
    ConfigRead("feedback_offset", A.INACTIVE_FOR_PROFILE,
               "buffer_state.cpp:370",
               note="FeedbackSharedBufferPolicy only"),

    # routing-table globals (routefunc.cpp InitializeRoutingMap)
    ConfigRead("read_request_begin_vc", A.FABRIC_DERIVED,
               "routefunc.cpp:1925"),
    ConfigRead("read_request_end_vc", A.FABRIC_DERIVED, "routefunc.cpp:1929"),
    ConfigRead("write_request_begin_vc", A.FABRIC_DERIVED,
               "routefunc.cpp:1933"),
    ConfigRead("write_request_end_vc", A.FABRIC_DERIVED,
               "routefunc.cpp:1937"),
    ConfigRead("read_reply_begin_vc", A.FABRIC_DERIVED, "routefunc.cpp:1941"),
    ConfigRead("read_reply_end_vc", A.FABRIC_DERIVED, "routefunc.cpp:1945"),
    ConfigRead("write_reply_begin_vc", A.FABRIC_DERIVED,
               "routefunc.cpp:1949"),
    ConfigRead("write_reply_end_vc", A.FABRIC_DERIVED, "routefunc.cpp:1953"),

    # traffic manager
    ConfigRead("sim_type", A.BACKEND_PROFILE, "trafficmanager.cpp:51",
               "latency"),
    ConfigRead("subnets", A.BACKEND_PROFILE,
               "trafficmanager.cpp:79; main.cpp:101; veritx_embed.cpp:255", 1),
    ConfigRead("read_request_subnet", A.BACKEND_PROFILE,
               "trafficmanager.cpp:82", 0),
    ConfigRead("read_reply_subnet", A.BACKEND_PROFILE,
               "trafficmanager.cpp:83", 0),
    ConfigRead("write_request_subnet", A.BACKEND_PROFILE,
               "trafficmanager.cpp:84", 0),
    ConfigRead("write_reply_subnet", A.BACKEND_PROFILE,
               "trafficmanager.cpp:85", 0),
    ConfigRead("use_read_write", A.BACKEND_PROFILE,
               "trafficmanager.cpp:132,134", 0,
               note="trace records carry dst/size directly"),
    ConfigRead("write_fraction", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:138,140",
               note="only consulted when use_read_write!=0 (pinned 0)"),
    ConfigRead("read_request_size", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:144,146",
               note="only consulted when use_read_write!=0 (pinned 0); "
                    "trace records carry packet sizes"),
    ConfigRead("read_reply_size", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:150,152",
               note="only consulted when use_read_write!=0 (pinned 0)"),
    ConfigRead("write_request_size", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:156,158",
               note="only consulted when use_read_write!=0 (pinned 0)"),
    ConfigRead("write_reply_size", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:162,164",
               note="only consulted when use_read_write!=0 (pinned 0)"),
    ConfigRead("packet_size", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:168,170",
               note="trace records are the packet authority; the runner "
                    "validates every packet against max_packet_flits and "
                    "no config packet_size is emitted"),
    ConfigRead("packet_size_rate", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:179,181",
               note="only used for synthetic packet-size distributions; "
                    "trace records carry sizes"),
    ConfigRead("injection_rate", A.BACKEND_PROFILE,
               "trafficmanager.cpp:216,218", 0.0,
               note="trace injection process ignores load; no background "
                    "demand traffic"),
    ConfigRead("injection_rate_uses_flits", A.BACKEND_PROFILE,
               "trafficmanager.cpp:222", 0),
    ConfigRead("traffic", A.WORKLOAD_DERIVED, "trafficmanager.cpp:227",
               note="standalone: trace(<workload>); serving pins uniform"),
    ConfigRead("class_priority", A.BACKEND_PROFILE,
               "trafficmanager.cpp:232,234", 0,
               note="dead with priority=none"),
    ConfigRead("injection_process", A.BACKEND_PROFILE,
               "trafficmanager.cpp:238", "bernoulli",
               note="only used by non-trace patterns; pinned anyway"),
    ConfigRead("sim_count", A.BACKEND_PROFILE, "trafficmanager.cpp:316", 1),
    ConfigRead("seed", A.EXECUTION_POLICY, "trafficmanager.cpp:325,329",
               note="standalone: per-run explicit or pinned 1; serving: "
                    "profile-pinned 1"),
    ConfigRead("sample_period", A.WORKLOAD_DERIVED, "trafficmanager.cpp:335",
               note="standalone: trace span + margin; serving pins 1000"),
    ConfigRead("max_samples", A.BACKEND_PROFILE, "trafficmanager.cpp:336", 1),
    ConfigRead("warmup_periods", A.BACKEND_PROFILE,
               "trafficmanager.cpp:337", 3),
    ConfigRead("measure_stats", A.BACKEND_PROFILE,
               "trafficmanager.cpp:339,341", 1),
    ConfigRead("pair_stats", A.BACKEND_PROFILE, "trafficmanager.cpp:344", 0),
    ConfigRead("latency_thres", A.BACKEND_PROFILE,
               "trafficmanager.cpp:346,348", 1000000000000000.0,
               note="effectively disabled so trace drains never abort"),
    ConfigRead("warmup_thres", A.BACKEND_PROFILE,
               "trafficmanager.cpp:352,354", 0.05),
    ConfigRead("acc_warmup_thres", A.BACKEND_PROFILE,
               "trafficmanager.cpp:358,360", 0.05),
    ConfigRead("stopping_thres", A.BACKEND_PROFILE,
               "trafficmanager.cpp:364,366", 0.05),
    ConfigRead("acc_stopping_thres", A.BACKEND_PROFILE,
               "trafficmanager.cpp:370,372", 0.05),
    ConfigRead("include_queuing", A.BACKEND_PROFILE,
               "trafficmanager.cpp:376", 1),
    ConfigRead("print_csv_results", A.BACKEND_PROFILE,
               "trafficmanager.cpp:378", 0),
    ConfigRead("deadlock_warn_timeout", A.BACKEND_PROFILE,
               "trafficmanager.cpp:379", 256),
    ConfigRead("watch_file", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:381", note="no watch output requested"),
    ConfigRead("watch_flits", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:386", note="no watch output requested"),
    ConfigRead("watch_packets", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:391", note="no watch output requested"),
    ConfigRead("stats_out", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:396", note="no stats file requested"),
    ConfigRead("injected_flits_out", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:409", note="no flow file requested"),
    ConfigRead("received_flits_out", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:415", note="no flow file requested"),
    ConfigRead("stored_flits_out", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:421", note="no flow file requested"),
    ConfigRead("sent_flits_out", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:427", note="no flow file requested"),
    ConfigRead("outstanding_credits_out", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:433", note="no flow file requested"),
    ConfigRead("ejected_flits_out", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:439", note="no flow file requested"),
    ConfigRead("active_packets_out", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:445", note="no flow file requested"),
    ConfigRead("used_credits_out", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:454", note="no flow file requested"),
    ConfigRead("free_credits_out", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:460", note="no flow file requested"),
    ConfigRead("max_credits_out", A.INACTIVE_FOR_PROFILE,
               "trafficmanager.cpp:466", note="no flow file requested"),
)


# ── per-target profile objects ──────────────────────────────────────────

@dataclass(frozen=True)
class BookSimCertifiedProfile:
    """One target's closed-world view of the audited config surface."""

    profile_id: str
    semantics_version: str
    audit: tuple[ConfigRead, ...] = BOOKSIM_CERTIFIED_CONFIG_AUDIT
    overrides: tuple[tuple[str, ParameterOwner, Any], ...] = ()

    def __post_init__(self):
        names = [r.name for r in self.audit]
        if len(set(names)) != len(names):
            dupes = sorted(n for n in set(names) if names.count(n) > 1)
            raise ValueError(f"audit has duplicate fields: {dupes}")
        known = {r.name for r in self.audit}
        for name, _owner, _value in self.overrides:
            if name not in known:
                raise ValueError(
                    f"profile override {name!r} is not in the audit")

    def read(self, name: str) -> ConfigRead:
        for row in self.audit:
            if row.name == name:
                return row
        raise KeyError(name)

    def owner_of(self, name: str) -> ParameterOwner:
        for override_name, owner, _value in self.overrides:
            if override_name == name:
                return owner
        return self.read(name).owner

    def active_names(self) -> frozenset[str]:
        return frozenset(
            row.name for row in self.audit
            if self.owner_of(row.name)
            is not ParameterOwner.INACTIVE_FOR_PROFILE)

    def inactive_names(self) -> frozenset[str]:
        return frozenset(row.name for row in self.audit
                         if self.owner_of(row.name)
                         is ParameterOwner.INACTIVE_FOR_PROFILE)

    def pinned_values(self) -> dict[str, Any]:
        """Explicit values for every BACKEND_PROFILE-owned field."""
        overrides = {name: (owner, value)
                     for name, owner, value in self.overrides}
        values: dict[str, Any] = {}
        for row in self.audit:
            owner, value = overrides.get(row.name, (row.owner, row.pin))
            if owner is ParameterOwner.BACKEND_PROFILE and value is not None:
                values[row.name] = value
        return values

    def ownership(self) -> dict[str, ParameterOwner]:
        """name -> owner for every active field (the closed table)."""
        return {row.name: self.owner_of(row.name)
                for row in self.audit
                if self.owner_of(row.name)
                is not ParameterOwner.INACTIVE_FOR_PROFILE}

    def source_of(self, name: str) -> str:
        return self.read(name).source


BOOKSIM_STANDALONE_PROFILE = BookSimCertifiedProfile(
    profile_id=BOOKSIM_CERTIFIED_PROFILE_ID,
    semantics_version=BOOKSIM_CERTIFIED_SEMANTICS_VERSION,
)

BOOKSIM_SERVING_PROFILE = BookSimCertifiedProfile(
    profile_id="CERTIFIED_SERVING_BOOKSIM2_V1",
    semantics_version="booksim2-fork+B3.7c-embedded-injection",
    overrides=(
        ("traffic", A.BACKEND_PROFILE, "uniform"),
        ("sample_period", A.BACKEND_PROFILE, 1000),
    ),
)


__all__ = [
    "BOOKSIM_CERTIFIED_CONFIG_AUDIT",
    "BOOKSIM_CERTIFIED_PROFILE_ID",
    "BOOKSIM_CERTIFIED_SEMANTICS_VERSION",
    "BOOKSIM_SERVING_PROFILE",
    "BOOKSIM_STANDALONE_PROFILE",
    "BookSimCertifiedProfile",
    "ConfigRead",
]
