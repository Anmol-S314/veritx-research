"""veritx_dse.core.deps — runtime dependency self-check (pure seam).

The CLI runs off PYTHONPATH in several environments (host venv, the
veritx-tools-base container, CI) where no installer ever verified that
``pyproject.toml [project].dependencies`` are present. A missing third-party
dist used to surface as a bare ``ModuleNotFoundError`` deep inside a command
— after simulations had already burned minutes (e.g. ``baseline`` ran every
topology, then died importing ``pydantic`` at the comparison stage).

This module derives the requirement list from the package metadata itself,
so adding a dependency to ``pyproject.toml`` automatically extends the
check: no package names are hardcoded here or in any caller. The CLI calls
:func:`missing_distributions` once at startup and fails fast, naming every
missing dist together with the fix, before any work runs.
"""

from __future__ import annotations

from pathlib import Path


def _dse_dir() -> Path:
    """dse/ directory (parent of the veritx_dse package)."""
    return Path(__file__).resolve().parent.parent.parent


def _naive_project_dependencies(text: str) -> list[str]:
    """Extract ``[project].dependencies`` without a TOML library.

    Bootstrap fallback for interpreters without stdlib ``tomllib``
    (e.g. the tools image's system Python 3.10): scan the ``[project]``
    section for the ``dependencies = [ ... ]`` array and collect the
    quoted strings. Full-line comments are ignored. This deliberately
    parses only what the check needs — not general TOML.
    """
    import re

    in_project = False
    in_array = False
    deps: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            in_project = line == "[project]"
            continue
        if not in_project:
            continue
        if not in_array:
            if re.match(r"dependencies\s*=", line):
                _, _, rest = line.partition("=")
                rest = rest.strip()
                if rest.startswith("["):
                    rest = rest[1:]
                    in_array = True
                else:
                    continue
            else:
                continue
        else:
            rest = line
        for m in re.finditer(r'''"([^"]+)"|'([^']+)' ''', rest):
            deps.append(m.group(1) if m.group(1) is not None else m.group(2))
        if "]" in rest:
            break
    return deps


def declared_dependencies(pyproject: Path | None = None) -> list[str]:
    """Raw requirement strings from ``[project].dependencies``.

    Returns [] when the metadata is unavailable (e.g. running from an
    installed wheel, where the installer already guaranteed deps) — the
    check degrades to a no-op instead of a false alarm.
    """
    proj = pyproject or (_dse_dir() / "pyproject.toml")
    try:
        text = proj.read_text()
    except OSError:
        return []
    try:
        import tomllib

        data = tomllib.loads(text)
        deps = data.get("project", {}).get("dependencies", [])
        return [d for d in deps if isinstance(d, str) and d.strip()]
    except ImportError:
        return _naive_project_dependencies(text)
    except ValueError:
        return []


def _split_requirement(req: str) -> tuple[str, str | None]:
    """(dist name, marker or None) without the ``packaging`` dependency.

    Falls back to this naive split when ``packaging`` is unavailable; when
    it is available the caller prefers ``packaging.requirements``.
    """
    body, _, marker = req.partition(";")
    name = body.strip().split("[")[0]
    for sep in ("<", ">", "=", "!", "~", " ", "\t"):
        name = name.split(sep)[0]
    name = name.strip()
    marker = marker.strip() or None
    return name, marker


def missing_distributions(requirements: list[str] | None = None) -> list[str]:
    """Requirement strings whose dist is not installed in this interpreter.

    Marker-guarded requirements for other platforms are skipped. Pure:
    no subprocess, no network, no imports of the checked packages.
    """
    import importlib.metadata as _md

    try:
        from packaging.requirements import Requirement as _Req
    except ImportError:
        _Req = None  # type: ignore[assignment]

    missing: list[str] = []
    reqs = declared_dependencies() if requirements is None else requirements
    for req in reqs:
        if _Req is not None:
            try:
                parsed = _Req(req)
            except Exception:
                continue  # unparseable: not ours to judge
            if parsed.marker is not None and not parsed.marker.evaluate():
                continue
            name = parsed.name
        else:
            # No `packaging`: cannot evaluate markers. Check the name anyway,
            # except for platform-gated requirements (name them and we would
            # false-alarm on platforms that correctly omit them).
            name, marker = _split_requirement(req)
            if not name:
                continue
            if marker and any(
                key in marker
                for key in ("python_version", "sys_platform",
                            "platform_system", "os_name")
            ):
                continue
        try:
            _md.version(name)
        except _md.PackageNotFoundError:
            missing.append(req)
    return missing
