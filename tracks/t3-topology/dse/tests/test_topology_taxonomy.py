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
from veritx_dse.model.topology_artifact import TopologyError

@pytest.fixture(scope="module")
def reg() -> dict:
    return yaml.safe_load(REGISTRY.read_text())

def _stages(reg, name) -> dict:
    return reg["families"][name]["stages"]

def test_tax_1_recognized_does_not_imply_authorable(reg):
    assert any(s["RECOGNIZED"] == "YES" and s["AUTHORABLE"] != "YES"
               for s in (_stages(reg, n) for n in reg["families"])), \
        "no witness: RECOGNIZED and AUTHORABLE are indistinguishable"
    assert _stages(reg, "dragonfly")["RECOGNIZED"] == "YES"
    assert _stages(reg, "dragonfly")["AUTHORABLE"] == "NO"

def test_tax_2_authorable_does_not_imply_materializable(reg):
    # The witness is the aggregate `gec` row: GEC is declarable in code, yet
    # no mode-independent materializer exists (MECS/hybrid still refuse).
    # fat_tree LEFT this witness when it gained a graph materializer.
    for fam in ("gec",):
        s = _stages(reg, fam)
        assert s["AUTHORABLE"] == "YES", fam
        assert s["MATERIALIZABLE"] == "NO", fam
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

def test_tax_3_materializable_does_not_imply_authorable(reg):
    s = _stages(reg, "ring")
    assert s["MATERIALIZABLE"] == "YES"
    assert s["AUTHORABLE"] == "NO"
    assert reg["families"]["ring"]["role"] == "TEST_FIXTURE"
    from veritx_dse.model.topology_artifact import materialize_family
    art = materialize_family(MaterializedFamily.RING, endpoint_count=4)
    assert len(art.routers) == 4
    assert "ring" not in {f.value for f in TopologyFamily}

def test_tax_3b_authorable_and_materializable_are_independent(reg):
    """TAX-3: neither stage implies the other.

    PHASE B.1 CHANGED THE WITNESSES, NOT THE LAW. This test used to cite
    `flatfly` as "materializable but not authorable" — true while the legacy
    `TopologyFamily` enum was the ONLY declaration authority, because flatfly
    is absent from it. Typed topology intent (FlatFlyIntent) is now a second
    declaration authority, so flatfly became AUTHORABLE=YES; keeping the old
    assertion would pin a claim the implementation no longer makes.

    The law is witnessed instead by the two families that still separate:
    `gec` is AUTHORABLE and not MATERIALIZABLE; `ring` is MATERIALIZABLE and
    not authorable.
    """
    gec = _stages(reg, "gec")
    assert gec["AUTHORABLE"] == "YES"
    assert gec["MATERIALIZABLE"] == "NO"
    ring = _stages(reg, "ring")
    assert ring["MATERIALIZABLE"] == "YES"
    assert ring["AUTHORABLE"] == "NO"

def test_tax_3c_flatfly_is_now_authorable_through_typed_intent(reg):
    """The declaration authority is two-fold: the legacy enum OR a registered
    typed topology intent. flatfly is absent from the enum and authorable
    anyway — so a check against the enum alone is a false NEGATIVE."""
    from veritx_dse.model.topology_intent import AUTHORABLE_INTENT_KINDS
    s = _stages(reg, "flatfly")
    assert s["MATERIALIZABLE"] == "YES"
    assert s["AUTHORABLE"] == "YES"
    assert "flatfly" not in {f.value for f in TopologyFamily}
    assert "flatfly" in AUTHORABLE_INTENT_KINDS

def test_tax_4_materializable_does_not_imply_routable(reg):
    for fam in ("ring",):
        s = _stages(reg, fam)
        assert s["MATERIALIZABLE"] == "YES", fam
        assert s["ROUTABLE"] == "NO", fam

def test_tax_5_backend_spelling_is_not_canonical_identity(reg):
    examples = reg["backend_spelling_boundary"]["examples"]
    assert any(e["canonical"] != e["booksim"] for e in examples)
    for name, row in reg["families"].items():
        assert "backend_projection" in row, name

def test_tax_5b_projection_map_names_real_backend_spellings(reg):
    proj = reg["families"]["concentrated_mesh"]["backend_projection"]
    assert proj["booksim"] == "cmesh"
    assert reg["families"]["custom"]["backend_projection"]["booksim"] == "anynet"

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

def test_unknown_family_fails_closed(reg):
    assert "hypercube" not in reg["families"]
    with pytest.raises(Exception):
        NocConfig(topology_family="hypercube")

def test_flatfly_shape_and_degree():
    art = materialize_flatfly(k=4, n=2, concentration=4)
    assert len(art.routers) == 16
    assert len(art.channels) == 96
    assert art.family == MaterializedFamily.FLATFLY
    for r in art.routers:
        assert r.seat_capacity == 4
        assert len([c for c in art.channels if c.src_router == r.router_id]) \
            == (4 - 1) * 2

def test_flatfly_is_pure_point_to_point():
    """Every channel has exactly one destination router (no taps)."""
    art = materialize_flatfly(k=3, n=2, concentration=1)
    seen = set()
    for c in art.channels:
        assert c.src_router != c.dst_router
        seen.add((c.src_router, c.dst_router))
    assert len(seen) == len(art.channels)

def test_flatfly_rejects_illegal_params():
    with pytest.raises(ValueError):
        materialize_flatfly(k=1, n=2)
    with pytest.raises(ValueError):
        materialize_flatfly(k=4, n=0)

def test_seal_1_flatfly_matches_the_historical_target():
    art = materialize_flatfly(k=4, n=2, concentration=4)
    assert len(art.routers) == 16
    assert {r.seat_capacity for r in art.routers} == {4}
    assert sum(r.seat_capacity for r in art.routers) == 64
    assert len(art.channels) == 96
    for r in art.routers:
        assert len([c for c in art.channels
                    if c.src_router == r.router_id]) == 6

def test_seal_1b_endpoint_universe_is_64_not_16():
    """The trap this guards: 16 ROUTERS must not be read as 16 ENDPOINTS.
    flatfly_64 carries 64 endpoints over 16 routers."""
    art = materialize_flatfly(k=4, n=2, concentration=4)
    assert len(art.routers) == 16
    assert sum(r.seat_capacity for r in art.routers) == 64
    assert len(art.routers) != 64, "must not imply 64 routers"

def test_seal_1c_attachment_capacity_follows_seat_capacity():
    """The attachment law is family-agnostic: it consumes routers and
    seat_capacity. 64 agents fit; 16 seats do not."""
    full = materialize_flatfly(k=4, n=2, concentration=4)
    seats_full = [(r.router_id, s) for r in full.routers
                  for s in range(r.seat_capacity)]
    assert len(seats_full) == 64
    assert len(seats_full) >= 64

    thin = materialize_flatfly(k=4, n=2, concentration=1)
    seats_thin = [(r.router_id, s) for r in thin.routers
                  for s in range(r.seat_capacity)]
    assert len(seats_thin) == 16
    assert len(seats_thin) < 64

def test_seal_3_concentration_changes_identity():
    """Same router graph, different c, must NOT collapse to one fabric
    identity — the seat capacity is part of the artifact."""
    a = materialize_flatfly(k=4, n=2, concentration=4)
    b = materialize_flatfly(k=4, n=2, concentration=2)
    assert a.topology_hash() != b.topology_hash()
    assert [(c.src_router, c.dst_router) for c in a.channels] == \
           [(c.src_router, c.dst_router) for c in b.channels]
    assert a.routers[0].seat_capacity != b.routers[0].seat_capacity

def test_seal_3b_concentration_is_owned_by_the_artifact():
    """Concentration lives on Router.seat_capacity inside the artifact, so
    the artifact owns it — not a second parallel authority."""
    art = materialize_flatfly(k=4, n=2, concentration=4)
    assert all(r.seat_capacity == 4 for r in art.routers)
    d = art.to_dict()
    assert {r["seat_capacity"] for r in d["routers"]} == {4}

def test_seal_3c_same_parameters_are_deterministic():
    a = materialize_flatfly(k=3, n=3, concentration=2)
    b = materialize_flatfly(k=3, n=3, concentration=2)
    assert a.topology_hash() == b.topology_hash()
    assert len(a.routers) == 27 and len(a.channels) == 27 * 6
    assert len(a.channels) == 2 * (27 * 6 // 2)

def test_tax_5c_backend_spellings_come_from_one_authority(reg):
    """Every registry `backend_projection.booksim` names a real fork
    spelling from family_registry.BOOKSIM_TOPOLOGIES, or is null for a
    family with no backend spelling (ring). Docs are generated from the
    authority: yaml saying `ftree` while code and the fork say `fly` is
    exactly the divergence this test forbids."""
    from veritx_dse.model.family_registry import BOOKSIM_TOPOLOGIES
    for name, row in reg["families"].items():
        spelling = row["backend_projection"]["booksim"]
        if spelling is None:
            continue
        assert spelling in BOOKSIM_TOPOLOGIES, (
            f"{name}: backend_projection.booksim={spelling!r} is not a "
            f"fork topology spelling {sorted(BOOKSIM_TOPOLOGIES)}")
