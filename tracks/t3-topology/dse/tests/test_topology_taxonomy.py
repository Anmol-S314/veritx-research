"""Topology taxonomy tests (TAX-1..TAX-6).

The tree carries two enums that disagree (TopologyFamily vs
MaterializedFamily). These tests prove that enum membership is NOT a
capability statement, and that the registry — not an enum-set comparison —
is the stage authority.

docs/product/topology-family-registry.yaml is the authority;
scripts/check_topology_family_registry.py enforces it in CI.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
REGISTRY = ROOT / "docs/product/topology-family-registry.yaml"

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.model.compile_model import NocConfig, TopologyFamily
from veritx_dse.model.topology_artifact import (
    MaterializedFamily,
    materialize_flatfly,
    materialize_topology,
)
# NOTE: topology_artifact defines its OWN TopologyError
# (ValueError, SemanticError) which is a DIFFERENT class from
# core.errors.TopologyError(VeritXError). The two do not catch each other.
# This tranche catches the raiser's own class; the collision is recorded as
# an unresolved blocker in IMPLEMENTATION-LEDGER.md, not fixed here.
from veritx_dse.model.topology_artifact import TopologyError


@pytest.fixture(scope="module")
def reg() -> dict:
    return yaml.safe_load(REGISTRY.read_text())


def _stages(reg, name) -> dict:
    return reg["families"][name]["stages"]


# ── TAX-1: RECOGNIZED does not imply AUTHORABLE ─────────────────────────

def test_tax_1_recognized_does_not_imply_authorable(reg):
    assert any(s["RECOGNIZED"] == "YES" and s["AUTHORABLE"] != "YES"
               for s in (_stages(reg, n) for n in reg["families"])), \
        "no witness: RECOGNIZED and AUTHORABLE are indistinguishable"
    # dragonfly is recognized (config + backend spelling) but not authorable.
    assert _stages(reg, "dragonfly")["RECOGNIZED"] == "YES"
    assert _stages(reg, "dragonfly")["AUTHORABLE"] == "NO"


# ── TAX-2: AUTHORABLE does not imply MATERIALIZABLE ─────────────────────

def test_tax_2_authorable_does_not_imply_materializable(reg):
    for fam in ("gec", "fat_tree"):
        s = _stages(reg, fam)
        assert s["AUTHORABLE"] == "YES", fam
        assert s["MATERIALIZABLE"] == "NO", fam
    # And the code agrees: declaring GEC fails at materialization, typed.
    with pytest.raises(TopologyError) as e:
        materialize_topology(None, NocConfig(topology_family=TopologyFamily.GEC))
    assert "no canonical materializer" in str(e.value)
    assert "topology-family-registry" in str(e.value)


def test_tax_2b_gec_stays_in_the_taxonomy(reg):
    """A missing materializer must NOT delete a family from the taxonomy."""
    assert _stages(reg, "gec")["RECOGNIZED"] == "YES"
    assert TopologyFamily.GEC in set(TopologyFamily), \
        "GEC was removed from declaration authority — that conflates " \
        "AUTHORABLE with MATERIALIZABLE"


# ── TAX-3: MATERIALIZABLE does not imply AUTHORABLE ─────────────────────

def test_tax_3_materializable_does_not_imply_authorable(reg):
    s = _stages(reg, "ring")
    assert s["MATERIALIZABLE"] == "YES"
    assert s["AUTHORABLE"] == "NO"
    assert reg["families"]["ring"]["role"] == "TEST_FIXTURE"
    # RING really is materializable ...
    from veritx_dse.model.topology_artifact import materialize_family
    art = materialize_family(MaterializedFamily.RING, endpoint_count=4)
    assert len(art.routers) == 4
    # ... and really is NOT in declaration authority.
    assert "ring" not in {f.value for f in TopologyFamily}


def test_tax_3b_flatfly_materializable_not_authorable(reg):
    s = _stages(reg, "flatfly")
    assert s["MATERIALIZABLE"] == "YES"
    assert s["AUTHORABLE"] == "NO"
    assert "flatfly" not in {f.value for f in TopologyFamily}


# ── TAX-4: MATERIALIZABLE does not imply ROUTABLE ───────────────────────

def test_tax_4_materializable_does_not_imply_routable(reg):
    for fam in ("torus", "ring"):
        s = _stages(reg, fam)
        assert s["MATERIALIZABLE"] == "YES", fam
        assert s["ROUTABLE"] == "NO", fam


# ── TAX-5: canonical id is not a backend spelling ───────────────────────

def test_tax_5_backend_spelling_is_not_canonical_identity(reg):
    examples = reg["backend_spelling_boundary"]["examples"]
    assert any(e["canonical"] != e["booksim"] for e in examples)
    # Every family carries an explicit one-way projection map.
    for name, row in reg["families"].items():
        assert "backend_projection" in row, name


def test_tax_5b_projection_map_names_real_backend_spellings(reg):
    proj = reg["families"]["concentrated_mesh"]["backend_projection"]
    assert proj["booksim"] == "cmesh"
    assert reg["families"]["custom"]["backend_projection"]["booksim"] == "anynet"


# ── TAX-6: no enum-set comparison is the capability authority ───────────

def test_tax_6_registry_matches_both_enums(reg):
    """The registry must cover every enum member — drift fails closed."""
    decl = {f.value for f in TopologyFamily}
    mat = {f.value for f in MaterializedFamily}
    for value in decl | mat:
        assert value in reg["families"], f"enum member {value!r} has no row"


def test_tax_6b_checker_passes():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_topology_family_registry.py")],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TAX-1..TAX-6" in r.stdout


def test_tax_6c_checker_detects_drift(tmp_path, monkeypatch):
    """A registry that claims an unhonourable stage must FAIL the checker."""
    bad = yaml.safe_load(REGISTRY.read_text())
    # Claim dragonfly is authorable although no intent schema exists.
    bad["families"]["dragonfly"]["stages"]["AUTHORABLE"] = "YES"
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.safe_dump(bad))
    src = (ROOT / "scripts/check_topology_family_registry.py").read_text()
    src = src.replace(
        'REGISTRY = REPO / "docs/product/topology-family-registry.yaml"',
        f'REGISTRY = Path({str(p)!r})')
    script = tmp_path / "check.py"
    script.write_text(src)
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).parent.parent)
    r = subprocess.run([sys.executable, str(script)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 1
    assert "dragonfly" in r.stdout


# ── unknown family fails closed ─────────────────────────────────────────

def test_unknown_family_fails_closed(reg):
    assert "hypercube" not in reg["families"]
    with pytest.raises(Exception):
        NocConfig(topology_family="hypercube")


# ── flatfly shape (the first non-mesh proof family) ─────────────────────

def test_flatfly_shape_and_degree():
    art = materialize_flatfly(k=4, n=2, concentration=4)
    assert len(art.routers) == 16                      # k**n
    assert len(art.channels) == 96                     # 2 * 48 undirected
    assert art.family == MaterializedFamily.FLATFLY
    for r in art.routers:
        assert r.seat_capacity == 4
        assert len([c for c in art.channels if c.src_router == r.router_id]) \
            == (4 - 1) * 2                             # (k-1)*n


def test_flatfly_is_pure_point_to_point():
    """Every channel has exactly one destination router (no taps)."""
    art = materialize_flatfly(k=3, n=2, concentration=1)
    seen = set()
    for c in art.channels:
        assert c.src_router != c.dst_router
        seen.add((c.src_router, c.dst_router))
    assert len(seen) == len(art.channels)              # no fan-out primitive


def test_flatfly_rejects_illegal_params():
    # _as_int raises ValueError (TopologyError subclasses ValueError, so a
    # TopologyError is also caught here — the fail-closed direction holds).
    with pytest.raises(ValueError):
        materialize_flatfly(k=1, n=2)
    with pytest.raises(ValueError):
        materialize_flatfly(k=4, n=0)
