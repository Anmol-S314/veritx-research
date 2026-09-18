"""Preset integrity at the `evaluate booksim` seam.

The bug these tests pin: `--k` had default=8, and the handler merged
`args.k` over preset params — so `dragonfly_72` (k=2) silently became a
16,512-node fabric and every preset whose k ≠ 8 was corrupted at the CLI
boundary while `presets.py` itself stayed correct.

Contract now:
  - named preset + no explicit flags  → exactly the preset architecture
  - named preset + explicit --k/--routing → REFUSE (presets are immutable)
  - raw backend name (no preset match) → requires explicit --k
  - node-count table: each preset resolves to its declared size
"""

import argparse
import pytest

from veritx_dse.model.presets import lookup_topo, topo_size
from veritx_dse.cli.cli import _resolve_eval_topology


def _args(**kw):
    base = dict(topo="dragonfly_72", k=None, routing=None)
    base.update(kw)
    return argparse.Namespace(**base)


# ── node-count table (reviewer's invariant list) ─────────────────────────

EXPECTED_NODES = {
    "mesh_4x4": 16,
    "mesh_8x8": 64,
    "torus_8x8": 64,
    "flatfly_64": 64,
    "gec_express_k8": 64,
    "gec_mecs_k8": 64,
    "gec_mesh_k8": 64,
    "fbfly_64": 64,
    "cmesh_64": 64,
    "fattree_k4n3": 64,
    "qtree_64": 64,
    "tree4_64": 64,
    "dragonfly_72": 72,
}


@pytest.mark.parametrize("name", sorted(EXPECTED_NODES))
def test_preset_resolves_to_declared_node_count(name):
    topo = lookup_topo(name)
    assert topo is not None, f"preset {name} vanished from presets.py"
    nodes, _links = topo_size(topo)
    assert nodes == EXPECTED_NODES[name], (
        f"preset {name}: resolved {nodes} nodes, declared "
        f"{EXPECTED_NODES[name]}")


# ── the corruption regression ────────────────────────────────────────────

def test_preset_untouched_when_k_unset():
    """k=None must NOT manufacture a default k over the preset's params."""
    topo, err = _resolve_eval_topology(_args())
    assert err is None
    assert topo.backend == "dragonflynew"
    assert topo.params["k"] == 2 and topo.params["n"] == 1
    nodes, _ = topo_size(topo)
    assert nodes == 72


def test_preset_keeps_own_name():
    topo, err = _resolve_eval_topology(_args(topo="fattree_k4n3"))
    assert err is None
    assert topo.name == "fattree_k4n3"
    assert topo.params == {"k": 4, "n": 3}


def test_preset_refuses_explicit_k_override():
    topo, err = _resolve_eval_topology(_args(k=8))
    assert topo is None and err is not None
    assert "immutable" in err


def test_preset_refuses_routing_override():
    topo, err = _resolve_eval_topology(_args(routing="ugal"))
    assert topo is None and err is not None
    assert "immutable" in err


# ── raw-backend form ─────────────────────────────────────────────────────

def test_raw_backend_with_explicit_k_builds():
    topo, err = _resolve_eval_topology(
        _args(topo="dragonflynew", routing="min", k=3))
    assert err is None
    assert topo.backend == "dragonflynew" and topo.params["k"] == 3


def test_raw_backend_alias_with_k_is_raw_form():
    """Backend alias + explicit k/routing = raw architecture, not the alias preset."""
    topo, err = _resolve_eval_topology(
        _args(topo="dragonflynew", routing="min", k=3))
    assert err is None
    assert topo.name.startswith("dragonflynew_")
    assert topo.params["k"] == 3


def test_backend_alias_bare_resolves_to_preset():
    topo, err = _resolve_eval_topology(_args(topo="mesh"))
    assert err is None
    nodes, _ = topo_size(topo)
    assert nodes == 16  # first mesh preset is mesh_4x4
