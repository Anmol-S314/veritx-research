"""Slice 34 §1 — the restored BookSim embedded diagnostic ABI is inert.

Commit A restores VeritX's own embedding-layer diagnostics
(``veritx_embed.{hpp,cpp}``) so the vendored ASTRA frontend can build against
the canonical BookSim fork at all.  That restoration is approved ONLY as a
diagnostic/build-ABI change, so these tests pin the property directly: the
restored surface must read simulator state that already exists and must not
participate in any routing, injection, scheduling, timing or VC decision.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
FORK = REPO / "third_party" / "booksim2" / "src"
HPP = FORK / "veritx_embed.hpp"
CPP = FORK / "veritx_embed.cpp"
#: the nested vendored copy must not be an authority
NESTED = (REPO / "third_party" / "astra-sim" / "extern" / "network_backend"
          / "booksim2" / "booksim2" / "src")

COUNTERS = ("_packets_requested", "_unicast_flits", "_mcast_deliveries",
            "_flits_retired", "_tails_retired")
#: the only functions allowed to mutate diagnostics
MUTATORS = ("_BuildUnicast", "_BuildMcastStream", "_RetireFlit")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _embed_class(hpp: str) -> str:
    start = hpp.index("class EmbedTM")
    end = hpp.index("};", start)
    return hpp[start:end]


def _braced(text: str, marker: str) -> str:
    """The brace-balanced body following ``marker`` (header or out-of-line)."""
    start = text.index(marker)
    brace = text.index("{", start + len(marker) - len(marker))
    brace = text.index("{", start)
    depth = 0
    for index in range(brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[brace:index + 1]
    raise AssertionError(f"unterminated body after {marker!r}")


def _function_body(cpp: str, name: str) -> str:
    marker = f"EmbedTM::{name}("
    return _braced(cpp, marker)


# ── the fork is the single authority ──────────────────────────────────────

def test_diagnostics_live_only_in_the_canonical_fork():
    assert HPP.is_file() and CPP.is_file()
    for name in ("veritx_embed.hpp", "veritx_embed.cpp"):
        # the nested copy stays untouched vendored third-party: it must NOT
        # carry the restored diagnostics
        nested = NESTED / name
        if not nested.is_file():
            continue
        assert "InFlightFlitCount" not in _text(nested), (
            f"{name} in the nested fork carries the diagnostic API; the "
            "nested copy must not be a second authority")


# ── no behavioural surface was added ──────────────────────────────────────

def test_embedtm_overrides_only_retirement():
    body = _embed_class(_text(HPP))
    overrides = set(re.findall(r"([A-Za-z_][A-Za-z0-9_:<>*& ]*?)\s*\([^;{]*\)\s*override", body))
    assert overrides == {"void _RetireFlit"}, \
        f"unexpected virtual overrides: {sorted(overrides)}"
    for forbidden in ("_Step", "_RoutePacket", "_Inject", "_GeneratePacket",
                      "_IssuePacket", "_VCAllocator", "_Arbiter",
                      "_GetNextPacketSize", "_OnPacketGenerated"):
        assert f"{forbidden}(" not in body, \
            f"EmbedTM must not override or add {forbidden}"


def test_every_diagnostic_accessor_is_const_and_read_only():
    body = _embed_class(_text(HPP))
    names = set(re.findall(
        r"(?:int64_t|int|bool|const std::map[^;{]*?)\s+([A-Z][A-Za-z0-9_]*)"
        r"\s*\([^)]*\)\s*const\s*\{", body))
    for required in ("InFlightFlitCount", "PartialQueueFlitCount",
                     "PacketsRequested", "UnicastFlitsConstructed",
                     "McastDeliveriesConstructed", "FlitsRetired",
                     "TailDeliveriesRecorded", "SampleOldestInFlight",
                     "HasInFlight", "Cycle", "NumNodes"):
        assert required in names, f"{required} is not a const accessor"
    for name in sorted(names):
        implementation = _braced(_embed_class(_text(HPP)), f"{name}(") \
            if f"{name}(" in _embed_class(_text(HPP)) else ""
        assert implementation, f"could not read {name}"
        # a read-only accessor may not assign to a simulator member
        mutation = re.search(r"(?<![=!<>+\-*/])_[a-z_][a-z0-9_]*\s*=[^=]",
                             implementation)
        assert mutation is None, \
            f"{name} mutates state: {mutation.group(0)!r}"


def test_diagnostic_counters_are_written_only_at_host_injection_and_retirement():
    cpp = _text(CPP)
    pattern = re.compile(
        r"(?:\+\+(?:%s))|(?:(?:%s)\s*\+=)"
        % ("|".join(COUNTERS), "|".join(COUNTERS)))
    sites: dict[str, int] = {}
    for name in MUTATORS:
        sites[name] = len(pattern.findall(_function_body(cpp, name)))
    assert sites["_BuildUnicast"] == 2, sites
    assert sites["_BuildMcastStream"] == 2, sites
    assert sites["_RetireFlit"] == 2, sites
    # every counter write in the whole translation unit is inside a mutator
    assert len(pattern.findall(cpp)) == sum(sites.values()) == 6, sites
    # the counter members are declared (initialised) exactly once each
    hpp = _text(HPP)
    for counter in COUNTERS:
        assert len(re.findall(re.escape(counter) + r"\s*=\s*0\s*;", hpp)) == 1, \
            f"{counter} must be declared exactly once in the header"


def test_counters_are_never_referenced_outside_the_embedding_layer():
    offenders = []
    for path in sorted(FORK.rglob("*")):
        if not path.is_file() or path.suffix not in (".cpp", ".hpp", ".cc", ".h"):
            continue
        if path.name.startswith("veritx_embed"):
            continue
        text = _text(path)
        for counter in COUNTERS:
            if counter in text:
                offenders.append((path.name, counter))
    assert offenders == [], (
        "diagnostic counters leak into the simulator core, so they could "
        f"influence routing/injection/timing: {offenders}")


def test_retirement_semantics_are_delegated_not_reimplemented():
    body = _function_body(_text(CPP), "_RetireFlit")
    assert "TrafficManager::_RetireFlit(f, dest)" in body
    delegate = body.index("TrafficManager::_RetireFlit(f, dest)")
    for counter in COUNTERS:
        first = body.find(counter)
        if first != -1:
            assert first > delegate, (
                f"{counter} is written before retirement is delegated, which "
                "would change retirement semantics")


def test_injection_functions_keep_their_flit_construction_unchanged():
    cpp = _text(CPP)
    for name, expected in (("_BuildUnicast", "Flit::New()"),
                           ("_BuildMcastStream", "Flit::New()")):
        body = _function_body(cpp, name)
        assert expected in body
        # no counter write may sit between flit construction and enqueueing
        last_construct = body.rindex("_partial_packets")
        for counter in COUNTERS:
            index = body.find(counter)
            if index != -1:
                assert index < last_construct, \
                    f"{counter} is written after packets are enqueued in {name}"


def test_canonical_fork_keeps_the_success_exit_code():
    """The canonical fork's exit semantics must not regress (MR12)."""
    main_cpp = _text(FORK / "main.cpp")
    assert "return result ? 0 : -1;" in main_cpp
