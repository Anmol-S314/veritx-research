"""Missing-capability refusals, machine-readable at the refusal site.

A refusal that says "no canonical X exists" is a GAP: the design asked for
something the system has no artifact for, and the honest next move is to
build that artifact. A refusal that says "cannot" is an IMPOSSIBILITY: no
artifact would make it true. The two look identical in prose, so the site
that already knows the difference must say so in a form a client can read.

``require_capability(capability, message)`` raises a core-owned typed
refusal tagged with the missing capability. ``declared_gaps()`` discovers
them by reading the package source, so a new tagged refusal appears in the
product without anyone remembering to register it, and
``tests/test_capability_gaps.py`` fails on an untagged gap-shaped refusal.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from veritx_dse.core.errors import MissingCapability, require_capability

#: Compatibility semantic token for resolved-fabric capability refusals.
RESOLVED_FABRIC_STAGE = "RESOLVED_FABRIC"

#: The package that owns the refusal sites.
_PACKAGE = Path(__file__).resolve().parent.parent

#: `require("id", ...)` — the id is the machine-readable capability.
#: `require_capability("id", ...)` — deliberately distinctive: the
#: package already has unrelated `require(...)` validators, and a loose
#: pattern would index those as gaps.
_REQUIRE = re.compile(r"""require_capability\(\s*["']([a-z0-9_]+)["']""")

#: Refusal phrasings that mean a capability is absent. A site using one of
#: these without a capability tag is an untagged gap, and the gate fails.
#: The bare phrase "no hardware" is deliberately absent: it matched the
#: returned calibration note "no hardware dataset in repo" (a value, not a
#: refusal). Genuine hardware-capability gaps read "no canonical ...".
GAP_PHRASES: tuple[str, ...] = (
    "no canonical",
    "has no isolation",
    "no selection/interleave",
    "not implemented",
)

#: Phrasings that are genuine impossibilities: no artifact would help.
#: Listed so the gate can tell a gap from a refusal that is doing its job.
IMPOSSIBLE_PHRASES: tuple[str, ...] = (
    "cannot be represented",
    "exceeds",
    "outside 0..",
    "overflows",
    "overlap",
    "consumes the whole",
    "unknown ",
    "is not a supported",
)


def classify(reason: str | None) -> str:
    """Classify a recorded refusal as NO_ARTIFACT or IMPOSSIBLE.

    Used for the corpus already on disk, which predates tagging. New
    refusals carry their own class and never reach this.
    """
    if not reason:
        return "UNKNOWN"
    text = reason.lower()
    for phrase in IMPOSSIBLE_PHRASES:
        if phrase in text:
            return "IMPOSSIBLE"
    for phrase in GAP_PHRASES:
        if phrase in text:
            return "NO_ARTIFACT"
    return "UNCLASSIFIED"


def _source_files() -> list[Path]:
    return sorted(_PACKAGE.rglob("*.py"))


def _docstring_lines(source: str) -> set[int]:
    """Lines covered by a genuine docstring.

    Documentation describes a gap; a refusal *is* a string literal too, so
    the distinction has to be structural. A docstring is only the first
    statement of a module, class or function body.
    """
    covered: set[int] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return covered

    def add(node: ast.AST) -> None:
        body = getattr(node, "body", None)
        if not body:
            return
        head = body[0]
        if not (isinstance(head, ast.Expr)
                and isinstance(head.value, ast.Constant)
                and isinstance(head.value.value, str)):
            return
        end = getattr(head, "end_lineno", head.lineno) or head.lineno
        covered.update(range(head.lineno, end + 1))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            add(node)
    return covered


def declared_gaps() -> list[dict[str, Any]]:
    """Every tagged refusal site, discovered from source."""
    out: list[dict[str, Any]] = []
    for path in _source_files():
        if path.name == Path(__file__).name:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _REQUIRE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            out.append({
                "capability": match.group(1),
                "source": path.relative_to(_PACKAGE).as_posix(),
                "line": line,
            })
    return out


def untagged_gap_sites() -> list[dict[str, Any]]:
    """Refusal sites that read as a gap but carry no capability tag.

    The gate turns this into a failure: an untagged gap is invisible to the
    product, which is the exact failure this module exists to prevent.
    """
    tagged = {(g["source"], g["line"]) for g in declared_gaps()}
    out: list[dict[str, Any]] = []
    for path in _source_files():
        if path.name == Path(__file__).name:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = source.splitlines()
        prose = _docstring_lines(source)
        # A tagged call spans lines: the message continues after the opening
        # paren, so the gap phrase can sit on a later line than the tag. Track
        # the enclosing statement instead of guessing.
        depth = 0
        tagged_until = 0
        for number, line in enumerate(lines, start=1):
            lowered = line.lower()
            depth += line.count("(") - line.count(")")
            if "require_capability(" in line:
                tagged_until = number + max(depth, 1) + 8
            if not any(phrase in lowered for phrase in GAP_PHRASES):
                continue
            if number <= tagged_until or "require_capability(" in line:
                continue
            # Prose that only documents a gap inside a comment is not a
            # refusal site.
            stripped = line.strip()
            if number in prose or stripped.startswith("#"):
                continue
            out.append({
                "source": path.relative_to(_PACKAGE).as_posix(),
                "line": number,
                "text": stripped[:160],
                "tagged": (path.relative_to(_PACKAGE).as_posix(), number) in tagged,
            })
    return [entry for entry in out if not entry["tagged"]]


def capability_gaps() -> dict[str, Any]:
    """The derived gap list the product serves."""
    return {
        "type": "veritx/CapabilityGaps/v1",
        "gaps": declared_gaps(),
        "note": (
            "A tagged refusal site: a design asked for a capability that has "
            "no canonical artifact. Building the artifact unblocks every "
            "configuration that requests it, including future ones. "
            "Untagged refusals are impossibilities or legacy prose; they are "
            "classified by shape, not by registry."
        ),
    }
