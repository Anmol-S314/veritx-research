"""Verified-PRD Integrity PR A — environment contract (§11).

Pins the reproducibility fixes the verified PRD demanded:

  * truthful interpreter floor: run creation fails loudly below the
    declared minimum (Gate A: silent incompatibility is how the uuid7
    defect survived);
  * UUIDv7 identity (ADR 0002) from stdlib only — valid, sortable, and
    NOT dependent on uuid.uuid7 (3.14+ stdlib);
  * declared runtime deps: pyproject names every third-party package the
    package actually imports (pydantic/numpy/scipy/skopt/yaml);
  * dependency lock identity: requirements.lock exists, is parseable, and
    its packages/versions agree with pyproject (consistency, not staleness).

These are contract tests at public seams: they do not mock subprocess or
patch internals.
"""
import importlib.metadata as importlib_metadata
import re
import uuid as uuid_module
from pathlib import Path

import pytest

import veritx_dse.core.runs as runs_mod
from veritx_dse.core.runs import new_run_id, _uuid7

DSE_DIR = Path(runs_mod.__file__).resolve().parents[2]


# ── Interpreter floor (Gate A) ───────────────────────────────────────────────

class TestInterpreterFloor:
    def test_run_create_rejects_below_floor(self, monkeypatch):
        monkeypatch.setattr(runs_mod.sys, "version_info", (3, 11, 4))
        with pytest.raises(runs_mod.RunError, match="requires Python >= 3.12"):
            runs_mod.assert_runtime_compatible()

    def test_floor_accepts_minimum(self, monkeypatch):
        monkeypatch.setattr(runs_mod.sys, "version_info", (3, 12, 0))
        runs_mod.assert_runtime_compatible()  # no raise

    def test_declared_floor_matches_enforced_floor(self):
        """pyproject requires-python and the runtime check must agree."""
        pyproject = (DSE_DIR / "pyproject.toml").read_text()
        m = re.search(r'requires-python\s*=\s*">=([\d.]+)"', pyproject)
        assert m, "pyproject.toml must declare requires-python"
        declared = tuple(int(x) for x in m.group(1).split("."))
        assert declared == runs_mod._RUNTIME_FLOOR


# ── UUIDv7 identity (ADR 0002) without 3.14 stdlib ──────────────────────────

class TestUuid7:
    def test_valid_uuid(self):
        assert uuid_module.UUID(new_run_id()).version == 7

    def test_variant_rfc4122(self):
        u = _uuid7()
        assert (u.int >> 62) & 0b11 == 0b10

    def test_unique_across_burst(self):
        ids = {new_run_id() for _ in range(2000)}
        assert len(ids) == 2000

    def test_embeds_wallclock_timestamp(self):
        """ADR 0002's point: ids sort by creation time — which holds only
        if the 48-bit unix-ms timestamp is genuinely embedded. Verify the
        embedded timestamp sits inside the wall-clock window around now."""
        import time
        before_ms = time.time_ns() // 1_000_000
        u = _uuid7()
        after_ms = time.time_ns() // 1_000_000
        embedded_ms = u.int >> 80
        assert before_ms <= embedded_ms <= after_ms

    def test_does_not_require_uuid7_stdlib(self):
        """The implementation must be ours: uuid.uuid7 exists only on 3.14+
        but the package declares >=3.12 (the snapshot's independent env
        failed here). monkeypatch the attr away and require it still works."""
        import sys
        if hasattr(uuid_module, "uuid7"):
            saved = uuid_module.uuid7
            del uuid_module.uuid7
            try:
                assert uuid_module.UUID(new_run_id()).version == 7
            finally:
                uuid_module.uuid7 = saved
        else:
            assert uuid_module.UUID(new_run_id()).version == 7


# ── Declared runtime dependencies (Gate A) ──────────────────────────────────

_EXPECTED_DEPS = {
    "pydantic": "core/spec.py boundary models",
    "numpy": "synthesis + certification tools",
    "scipy": "MILP route/VC solving",
    "scikit-optimize": "bo_synthesizer",
    "PyYAML": "network-config overlay in cli (imports as yaml)",
}

# distribution name → import name (metadata lookups use distributions)
_IMPORT_NAME = {"scikit-optimize": "skopt", "PyYAML": "yaml"}


class TestDeclaredDependencies:
    @pytest.mark.parametrize("pkg", sorted(_EXPECTED_DEPS))
    def test_third_party_import_has_metadata(self, pkg):
        """Import the real module and confirm installed metadata — the
        missing-declaration failure mode, reproduced, for every dep."""
        __import__(_IMPORT_NAME.get(pkg, pkg))
        assert importlib_metadata.version(pkg) is not None

    def test_pyproject_declares_all_required_deps(self):
        pyproject = (DSE_DIR / "pyproject.toml").read_text()
        deps_block = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
        for pkg in _EXPECTED_DEPS:
            assert pkg.lower() in deps_block.lower(), \
                f"{pkg} imported but undeclared"


# ── Dependency lock identity (§11.3) ─────────────────────────────────────────

class TestDependencyLock:
    def test_lock_file_exists_and_parses(self):
        lock = DSE_DIR / "requirements.lock"
        assert lock.is_file()
        pinned = {}
        for line in lock.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, _, version = line.partition("==")
            assert version, f"lock line is not a == pin: {line!r}"
            pinned[name.lower()] = version
        assert set(pinned) == {p.lower() for p in _EXPECTED_DEPS}

    def test_lock_satisfies_pyproject_floors(self):
        """Consistency, not staleness: every pin satisfies its pyproject
        floor (major.minor comparison)."""
        pyproject = (DSE_DIR / "pyproject.toml").read_text()
        floors = dict(re.findall(
            r'"([\w-]+)>=([\d.]+)"', pyproject))
        floors.pop("setuptools", None)  # build-system requirement, not runtime
        floors.pop("pytest", None) and None
        floors = {k.lower(): v for k, v in floors.items()
                  if k.lower() in {p.lower() for p in _EXPECTED_DEPS}}
        assert set(floors) == {p.lower() for p in _EXPECTED_DEPS}, \
            "pyproject floors must cover exactly the declared runtime deps"
        lock = (DSE_DIR / "requirements.lock").read_text()
        pins = dict(re.findall(r"^([\w-]+)==([\d.]+)$", lock, re.M))
        pins = {k.lower(): v for k, v in pins.items()}
        for name, floor in floors.items():
            pinned = [int(x) for x in pins[name.lower()].split(".")[:2]]
            need = [int(x) for x in floor.split(".")[:2]]
            assert pinned >= need, f"{name} {pins[name.lower()]} < >= {floor}"

    def test_provenance_includes_lock_identity(self, tmp_path, monkeypatch):
        """§11.3: a run's provenance identifies the dependency lock."""
        monkeypatch.setattr(runs_mod, "_LOCK_PATH", DSE_DIR / "requirements.lock")
        prov = runs_mod.capture_provenance(tmp_path, ["argv"])
        ident = prov["python_dependency_lock"]
        assert ident["requirements.lock.sha256"], "lock hash must be captured"
        assert len(ident["requirements.lock.sha256"]) == 64

    def test_provenance_survives_missing_lock(self, tmp_path, monkeypatch):
        monkeypatch.setattr(runs_mod, "_LOCK_PATH",
                            tmp_path / "nonexistent.lock")
        prov = runs_mod.capture_provenance(tmp_path, ["argv"])
        assert prov["python_dependency_lock"]["requirements.lock.sha256"] is None
