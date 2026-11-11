"""veritx_dse.model.address_permission — M1 Address & Permission (STAGE 1 §4.1).

Rationale: docs/design/mesh-stage1-schema-compiler-scope.md §4.1.
Frozen input struct in -> Verdict out. No ``CompileRequestV4``, no
``topology_intent`` in the imports (module-isolation contract, §8.3).

Owns: range overlap/exclusivity, singleton-vs-STRIPED selection legality
against agent counts, and initiator→target permission coverage.

Initiator × region security model (replaces the range-keyed stub):
  * Initiator key = `agent_idx` (Agent GROUP). The NI/ingress asserts it
    from the physical port; it is never inferred from drawing proximity.
    All instances of a group share the group's policy (documented
    limitation; per-instance discrimination is future work).
  * Policy key = `(agent_idx, address_range)`. Two groups declaring rights
    for the same range now COMPILE and differ behaviorally. The same
    `(agent_idx, range)` defined twice is a policy conflict (INVALID).
  * Per-initiator R/W + `atomic` (only when the group's protocol is
    `axi5`). Default-deny: no `(initiator, range)` entry => denied; no
    entry for unmapped => ERROR; unknown `req_id` => denied.
  * Burst containment = DENY: a burst whose `[addr, addr+len)` is not
    fully inside the hit region is denied (error completion, never
    forwarded, `target_oh` suppressed). No split; combinational decoder
    leaves no stranded outstanding — each cycle is independent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.model.agent_intent_v4 import PermissionWindow
from veritx_dse.model.compile_model import AddressRange


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str | None = None
    findings: tuple[str, ...] = ()
    status: str = "INVALID"


@dataclass(frozen=True)
class TrafficRequirement:
    """The permission-relevant projection of a TrafficProfile."""

    traffic_class: str
    is_write: bool
    is_read: bool
    is_atomic: bool = False
    initiator_idx: int | None = None


@dataclass(frozen=True)
class InitiatorPolicy:
    """One `(agent_idx, address_range)` permission claim.

    `agent_idx` is the trusted ingress-asserted GROUP identity, never an
    address or drawing hint. `readable`/`writable`/`atomic` are the rights
    that group has in that region. Missing entry => default-deny.
    """

    agent_idx: int
    address_range: str
    readable: bool = True
    writable: bool = True
    atomic: bool = False

    def __post_init__(self):
        if type(self.agent_idx) is not int or isinstance(self.agent_idx, bool):
            raise ValueError(
                f"InitiatorPolicy.agent_idx must be an int, got "
                f"{type(self.agent_idx).__name__} {self.agent_idx!r}")
        if self.agent_idx < 0:
            raise ValueError(
                f"InitiatorPolicy.agent_idx must be >= 0, got {self.agent_idx}")
        if not isinstance(self.address_range, str) or not self.address_range:
            raise ValueError("InitiatorPolicy.address_range must be a non-empty string")
        for name in ("readable", "writable", "atomic"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(
                    f"InitiatorPolicy.{name} must be a bool, got "
                    f"{type(getattr(self, name)).__name__}")


@dataclass(frozen=True)
class AddressPermissionInput:
    ranges: tuple[AddressRange, ...]
    windows: tuple[PermissionWindow, ...] = ()
    agent_counts: tuple[int, ...] = ()
    traffic: tuple[TrafficRequirement, ...] = ()
    attachment_hash: str = ""
    unmatched_policy: str = "ERROR"
    initiator_policies: tuple[InitiatorPolicy, ...] = ()
    initiator_protocols: tuple[tuple[int, str | None], ...] = ()


@dataclass(frozen=True)
class DecodeProjection:
    """One canonical decode row (address bounds + selection, no endpoints).

    A pure projection of the input ranges: endpoint materialization stays with
    ``derive_address_decode`` over the attachment.
    """

    name: str
    base: int
    size: int
    target_agent_group: int
    selection_policy: str | None
    target_instance_index: int | None
    interleave_bytes: int | None


def _is_write_class(name: str) -> bool:
    lowered = name.lower()
    return ("write" in lowered or "invalidate" in lowered
            or lowered == "wb" or lowered.endswith("_wb"))


def _is_read_class(name: str) -> bool:
    return "read" in name.lower()


def _is_atomic_class(name: str) -> bool:
    return "atomic" in name.lower()


def _synthesize_policies(inp: AddressPermissionInput) -> tuple[InitiatorPolicy, ...]:
    """Combine legacy `windows` (no identity) and `initiator_policies`.

    Legacy `windows` are treated as initiator 0 (single-initiator
    back-compat). A caller mixing both is required to make every
    (agent_idx, range) unique; callers that pass only `initiator_policies`
    are the new multi-initiator path.
    """
    out: list[InitiatorPolicy] = []
    for window in getattr(inp, "windows", ()) or ():
        # Duck-typed: a PermissionWindow has no agent_idx; if the caller
        # already passed an InitiatorPolicy via `windows`, use its idx.
        idx = getattr(window, "agent_idx", None)
        if idx is None:
            idx = 0
        out.append(InitiatorPolicy(
            agent_idx=int(idx),
            address_range=str(window.address_range),
            readable=bool(getattr(window, "readable", True)),
            writable=bool(getattr(window, "writable", True)),
            atomic=bool(getattr(window, "atomic", False)),
        ))
    for p in getattr(inp, "initiator_policies", ()) or ():
        out.append(p)
    return tuple(out)


def check_address_permission(inp: AddressPermissionInput) -> Verdict:
    """Validate overlap, selection policy, initiator identity and coverage."""
    if inp.unmatched_policy != "ERROR":
        return Verdict(
            ok=False,
            reason=f"unmatched_policy {inp.unmatched_policy!r} is not "
            f"supported: only 'ERROR' exists (UnmatchedAddressPolicy.ERROR)")

    # Range integrity: known targets, selection legality against counts.
    ranges = inp.ranges
    counts = inp.agent_counts
    names = [r.name for r in ranges]
    if len(set(names)) != len(names):
        dupes = sorted(n for n in names if names.count(n) > 1)
        return Verdict(
            ok=False,
            reason=f"address map has duplicate range names {dupes}")
    for r in ranges:
        if not 0 <= r.target_agent_idx < len(counts):
            return Verdict(
                ok=False,
                reason=f"address range {r.name!r} targets agent group "
                f"{r.target_agent_idx}, outside the design's "
                f"{len(counts)} groups")
        count = counts[r.target_agent_idx]
        if count > 1 and r.selection_policy is None:
            return Verdict(
                ok=False,
                reason=f"address range {r.name!r} targets {count} "
                f"instances without explicit FIXED_INSTANCE or STRIPED "
                f"selection")
        if count == 1 and r.selection_policy is not None:
            return Verdict(
                ok=False,
                reason=f"address range {r.name!r} specifies a selection "
                f"policy for a singleton target group")

    # Overlap: pairwise over base-sorted ranges; the message names both
    # ranges (mirror of address_decode._validate_entries wording).
    ordered = sorted(ranges, key=lambda r: (r.base, r.size, r.name))
    for prev, cur in zip(ordered, ordered[1:]):
        if prev.base + prev.size > cur.base:
            return Verdict(
                ok=False,
                reason=f"address ranges {prev.name!r} and {cur.name!r} "
                f"overlap ({prev.base}+{prev.size} > {cur.base})")

    policies = _synthesize_policies(inp)
    known = set(names)

    # Protocol map (optional; missing => atomic not supported).
    protocol_of: dict[int, str | None] = {}
    for idx, fam in getattr(inp, "initiator_protocols", ()) or ():
        protocol_of[int(idx)] = fam

    # Initiator identity + range + duplicate/conflict + atomic checks.
    seen: dict[tuple[int, str], InitiatorPolicy] = {}
    for p in policies:
        if not 0 <= p.agent_idx < len(counts):
            return Verdict(
                ok=False,
                reason=f"permission policy for range "
                f"{p.address_range!r} names initiator group "
                f"{p.agent_idx}, outside the design's {len(counts)} "
                f"groups (missing/invalid identity)")
        if p.address_range not in known:
            return Verdict(
                ok=False,
                reason=f"permission window names unknown address range "
                f"{p.address_range!r}; declared ranges are "
                f"{sorted(known)}")
        key = (p.agent_idx, p.address_range)
        if key in seen:
            prev = seen[key]
            if (prev.readable, prev.writable, prev.atomic) != (
                    p.readable, p.writable, p.atomic):
                return Verdict(
                    ok=False,
                    reason=f"permission policy conflict for "
                    f"(initiator {p.agent_idx}, range "
                    f"{p.address_range!r}): "
                    f"readable={prev.readable} writable={prev.writable} "
                    f"atomic={prev.atomic} vs "
                    f"readable={p.readable} writable={p.writable} "
                    f"atomic={p.atomic} (one authority per "
                    f"(initiator, range); declared more than once)")
            return Verdict(
                ok=False,
                reason=f"permission policy for range "
                f"{p.address_range!r} (initiator {p.agent_idx}) is "
                f"declared more than once (one authority per "
                f"(initiator, range))")
        seen[key] = p
        if getattr(p, "atomic", False):
            fam = protocol_of.get(p.agent_idx)
            # `None` inherits Agent.protocol literal (e.g. "AXI"); only
            # an explicitly declared axi5 satisfies atomic.
            if fam is None:
                return Verdict(
                    ok=False,
                    reason=f"permission policy for range "
                    f"{p.address_range!r} (initiator {p.agent_idx}) "
                    f"requests atomic access, but the initiator's "
                    f"protocol is not 'axi5' (atomic only when the "
                    f"protocol supports it)")
            if str(fam).strip().lower() != "axi5":
                return Verdict(
                    ok=False,
                    reason=f"permission policy for range "
                    f"{p.address_range!r} (initiator {p.agent_idx}) "
                    f"requests atomic access, but the initiator's "
                    f"protocol is {fam!r} (atomic only when the "
                    f"protocol supports it)")

    # Permission coverage (per-initiator).
    # Group policies by range for the existential check.
    by_range: dict[str, list[InitiatorPolicy]] = {}
    for p in policies:
        by_range.setdefault(p.address_range, []).append(p)

    for req in inp.traffic:
        used_read = req.is_read or not req.is_write
        used_write = req.is_write or not req.is_read
        used_atomic = getattr(req, "is_atomic", False) or _is_atomic_class(req.traffic_class)
        if req.initiator_idx is not None:
            # Traffic attributed to one initiator: check that initiator's
            # policies only. Ranges without an entry are default-deny at
            # runtime, but a compile-time read/write against an entry that
            # denies it is a forward-declared violation of the intended
            # access (INVALID), matching §5.3.
            for p in policies:
                if p.agent_idx != req.initiator_idx:
                    continue
                if not p.readable and used_read:
                    return Verdict(
                        ok=False,
                        reason=f"traffic class {req.traffic_class!r} may read "
                        f"range {p.address_range!r}, but the permission "
                        f"window declares it unreadable")
                if not p.writable and used_write:
                    return Verdict(
                        ok=False,
                        reason=f"traffic class {req.traffic_class!r} may write "
                        f"range {p.address_range!r}, but the permission "
                        f"window declares it read-only")
                if not p.atomic and used_atomic:
                    return Verdict(
                        ok=False,
                        reason=f"traffic class {req.traffic_class!r} may use "
                        f"atomic on range {p.address_range!r}, but the "
                        f"permission window does not permit atomic")
        else:
            # Unattributed traffic: fail only if no initiator permits the
            # needed direction for a range. This lets two initiators with
            # opposite rights for one range compile; runtime then denies
            # the initiator that lacks the right.
            for range_name, plist in by_range.items():
                if used_read and not any(pp.readable for pp in plist):
                    return Verdict(
                        ok=False,
                        reason=f"traffic class {req.traffic_class!r} may read "
                        f"range {range_name!r}, but the permission "
                        f"window declares it unreadable")
                if used_write and not any(pp.writable for pp in plist):
                    return Verdict(
                        ok=False,
                        reason=f"traffic class {req.traffic_class!r} may write "
                        f"range {range_name!r}, but the permission "
                        f"window declares it read-only")
                if used_atomic and not any(pp.atomic for pp in plist):
                    return Verdict(
                        ok=False,
                        reason=f"traffic class {req.traffic_class!r} may use "
                        f"atomic on range {range_name!r}, but no "
                        f"initiator permits atomic there")
    return Verdict(ok=True, findings=())


def build_decode_entries(
        inp: AddressPermissionInput) -> tuple[DecodeProjection, ...]:
    """The canonical decode projection (bounds + selection, sorted).

    Callers project onto an attachment (endpoint ids) afterwards; this module
    never invents endpoint outcomes.
    """
    verdict = check_address_permission(inp)
    if not verdict.ok:
        raise ValueError(f"cannot project an invalid address map: "
                         f"{verdict.reason}")
    return tuple(DecodeProjection(
        name=r.name, base=r.base, size=r.size,
        target_agent_group=r.target_agent_idx,
        selection_policy=r.selection_policy,
        target_instance_index=r.target_instance_index,
        interleave_bytes=r.interleave_bytes)
        for r in sorted(inp.ranges, key=lambda r: (r.base, r.size, r.name)))


__all__ = [
    "AddressPermissionInput", "DecodeProjection", "InitiatorPolicy",
    "TrafficRequirement", "Verdict", "build_decode_entries",
    "check_address_permission",
]
