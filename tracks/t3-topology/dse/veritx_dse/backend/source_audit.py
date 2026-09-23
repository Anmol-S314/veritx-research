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


__all__ = [
    "CONFIG_READ_FREE_RE", "CONFIG_READ_RE", "DriftReport", "ReadOccurrence",
    "SOURCE_EXTENSIONS", "SourceAuditError", "audit_profile_reads",
    "observed_fields", "scan_config_reads",
]
