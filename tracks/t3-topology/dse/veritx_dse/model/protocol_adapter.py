"""veritx_dse.model.protocol_adapter — M4 Protocol Adapter (STAGE 1 §4.4).

Rationale: docs/design/mesh-stage1-schema-compiler-scope.md §4.4.
Frozen input struct in -> Verdict out. No ``CompileRequestV4``, no
``topology_intent`` in the imports (module-isolation contract, §8.3).
Also governed by docs/design/mesh-stage3-rtl-params-scope.md §3.1-3.2
(AdapterFactory).

Owns the closed protocol vocabulary (replacing the free-string
``Agent.protocol``), the burst-split family gate (§5.9), and the
``adapter_requirements`` tuple a later emitter consumes. The hardware is
built by the ``AdapterFactory`` deep module
(``veritx_dse.product.adapter_factory_rtl``).

Family wrappers (all realized; typed ``ADAPTER_UNSUPPORTED`` is kept only
for future families):

* ``axi5`` — AXI5 full adapter realized by AdapterFactory
  (``veritx_dse.product.adapter_factory_rtl``): AW/W/AR/R/B channels with
  AxID/AxLEN/AxSIZE/AxBURST/AxLOCK/AxCACHE/AxPROT/AxQOS/AxREGION/AxDOMAIN/
  AxATOMIC/AxDVMType, WSTRB/WLAST, BRESP/RRESP, exclusive and atomic
  transaction boundary semantics, coherency state, DVM and RSOS gated on
  declared enables, ID tracking, width split/merge, checker assertions.
  Not claimed: certification to any AMBA compliance suite;
  ``final_implementation`` stays False.
* ``chi`` — CHI Full-Profile adapter realized by AdapterFactory: REQ/RSP/
  SNP/DAT channel map from ``opcode[1:0]``, reorder depth, QoS arbitration
  with HOL bypass, byte-enable filtering, QoS credit counting,
  CT/legacy B/C/T profile handling, coherency FSM, DWT and Expiry,
  P-Credit and RSOS handling, DVM, checker assertions.
  Not claimed: an AMBA CHI compliance suite result;
  ``final_implementation`` stays False.
* ``tilelink`` — TileLink-1.8.1 UL+UH+C adapter realized by AdapterFactory:
  A/B/C/D/E channels, BCEB and RMW hints, sink FIFO, per-tap credits,
  formal legality assertions.
  Not claimed: a TileLink compliance suite result;
  ``final_implementation`` stays False.
* ``custom`` — protocol-neutral burst/ordering shim. A custom adapter
  requires at least one explicitly declared param: a burst param
  (``split_at``) or an ``ordering`` param. No hidden defaults are
  invented — a custom intent with neither is INVALID at compile
  (``PACKET_FORMAT`` owner stage), never an emitted default.
"""
from __future__ import annotations

from dataclasses import dataclass

from veritx_dse.model.agent_intent_v4 import (
    PROTOCOL_VOCAB, AgentIntentV4, ProtocolFamily,
)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str | None = None
    findings: tuple[str, ...] = ()
    status: str = "INVALID"


@dataclass(frozen=True)
class ProtocolInput:
    intents: tuple[AgentIntentV4, ...]
    data_width: int = 256
    addr_width: int = 64
    protocol_vocab: tuple[str, ...] = PROTOCOL_VOCAB


#: Families whose adapter implements a burst split (``split_at`` is a
#: legal knob for these). CHI/TileLink size their transfers from
#: ``DATA_W``/SIZE and forbid ``split_at`` so an inapplicable knob is
#: INVALID, never ignored.
BURST_SPLIT_FAMILIES: tuple[ProtocolFamily, ...] = (
    ProtocolFamily.AXI5, ProtocolFamily.CUSTOM)
#: Legacy singular name kept for import compatibility: AXI5 is the
#: historic burst-split family.
BURST_SPLIT_FAMILY = ProtocolFamily.AXI5

#: Blocker prefix: the named family has no wrapper module in the repo.
ADAPTER_UNSUPPORTED = "ADAPTER_UNSUPPORTED"

#: Families with no wrapper anywhere in the repo. After the M4
#: AdapterFactory shipped CHI/TileLink/custom wrappers, this is empty:
#: every closed-vocabulary family has a real shim. The constant is kept
#: so older importers keep working; ``adapter_blockers`` therefore
#: returns ``()`` for any in-vocabulary intent.
UNSUPPORTED_FAMILIES: tuple[ProtocolFamily, ...] = ()


def check_protocol(inp: ProtocolInput) -> Verdict:
    """Validate the closed vocabulary and family-specific knobs."""
    if inp.data_width < 8 or inp.addr_width < 8:
        return Verdict(
            ok=False,
            reason=f"protocol widths must be >= 8 bits, got data_width="
            f"{inp.data_width}, addr_width={inp.addr_width}")
    for intent in inp.intents:
        protocol = intent.protocol
        if protocol is not None:
            if not isinstance(protocol, ProtocolFamily) \
                    or protocol.value not in inp.protocol_vocab:
                return Verdict(
                    ok=False,
                    reason=f"agent group {intent.agent_idx} declares "
                    f"unknown protocol family {protocol!r}: expected one "
                    f"of {sorted(inp.protocol_vocab)}")
        if intent.split_at is not None and protocol not in BURST_SPLIT_FAMILIES:
            declared = (protocol.value if protocol is not None
                        else "the inherited Agent.protocol literal")
            return Verdict(
                ok=False,
                reason=f"agent group {intent.agent_idx} declares "
                f"split_at={intent.split_at} for {declared}; only "
                f"axi5/custom implement a burst split — "
                f"declare protocol 'axi5' or 'custom' with the split, "
                f"or drop it (an inapplicable knob is INVALID, "
                f"never ignored)")
        # Custom needs an explicit burst or ordering param (no hidden
        # defaults). A bare ``protocol="custom"`` intent declares neither,
        # so the factory would have to invent both — refused at compile.
        if protocol == ProtocolFamily.CUSTOM \
                and intent.split_at is None and intent.ordering is None:
            return Verdict(
                ok=False,
                reason=f"agent group {intent.agent_idx} declares "
                f"protocol 'custom' without a burst (split_at) or "
                f"ordering param — custom requires an explicitly declared "
                f"burst/ordering param; no hidden defaults are invented")
    findings: tuple[str, ...] = ()
    for intent in inp.intents:
        if intent.max_outstanding is not None \
                and intent.ordering is None:
            findings = findings + (
                f"agent group {intent.agent_idx} declares "
                f"max_outstanding={intent.max_outstanding} without an "
                f"ordering mode — no ordering promise is invented; "
                f"declare 'strong', 'relaxed' or 'raw'",
            )
    return Verdict(ok=True, findings=findings)


def adapter_requirements(inp: ProtocolInput) -> tuple[str, ...]:
    """Requirement names a hypothetical emitter consumes (sorted, unique)."""
    requirements: set[str] = set()
    for intent in inp.intents:
        if intent.protocol is not None:
            requirements.add(f"protocol-shim:{intent.protocol.value}")
        if intent.protocol in BURST_SPLIT_FAMILIES \
                and intent.split_at is not None:
            requirements.add("burst-split")
        if intent.protocol == ProtocolFamily.CHI:
            requirements.add("chi:request-size-alignment")
            requirements.add("chi:channel-map:req/rsp/snp/dat")
            requirements.add("chi:channel-map")
        if intent.protocol == ProtocolFamily.TILELINK:
            requirements.add("tilelink:ul-framing")
            requirements.add("tilelink:request-response-framing")
        if intent.protocol == ProtocolFamily.CUSTOM:
            if intent.split_at is not None:
                requirements.add("custom:burst")
            if intent.ordering is not None:
                requirements.add(f"custom:ordering:{intent.ordering.value}")
        if intent.max_outstanding is not None:
            requirements.add("outstanding-credit")
        if intent.ordering is not None:
            requirements.add(f"ordering:{intent.ordering.value}")
    return tuple(sorted(requirements))


def adapter_blockers(inp: ProtocolInput) -> tuple[str, ...]:
    """Blocker ids for intents whose family has no wrapper (typed failures).

    One entry per agent group declaring a protocol with no repo wrapper,
    e.g. ``ADAPTER_UNSUPPORTED:chi``. All closed-vocabulary families now
    have a real wrapper (axi5, chi, tilelink, custom), so for
    in-vocabulary intents this returns ``()``. The function is kept so
    callers that recorded blockers keep a typed (empty) answer rather
    than a silent skip.
    """
    if not UNSUPPORTED_FAMILIES:
        return ()
    blockers: list[str] = []
    for intent in inp.intents:
        protocol = intent.protocol
        if protocol in UNSUPPORTED_FAMILIES:
            blockers.append(
                f"{ADAPTER_UNSUPPORTED}:{protocol.value}")
    return tuple(sorted(blockers))


__all__ = [
    "ADAPTER_UNSUPPORTED", "BURST_SPLIT_FAMILIES", "BURST_SPLIT_FAMILY",
    "ProtocolInput", "Verdict",
    "UNSUPPORTED_FAMILIES", "adapter_blockers", "adapter_requirements",
    "check_protocol",
]
