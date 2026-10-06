"""Product presets for qualified structured families (§6).

dragonfly, fat_tree, flattened_butterfly, qtree and tree4 all reach
QUALIFIED in capability truth but had no shipped preset, so PRODUCT_WIRED
stayed NO. Each preset below is product UX over an existing authority —
never a new one: the request builds through the typed builders, compiles
through FabricCompiler, and normalizes back to its own family through the
same generation seam _product_wired uses.

Execution and qualification ride on capability truth (which probes these
families end to end); these tests prove the product path reaches the
compiler intact and the wiring predicate flips.
"""
from __future__ import annotations

import sys
from pathlib import Path

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.application.capability_truth import (  # noqa: E402
    capability_family_label,
)
from veritx_dse.application.fabric_compiler import (  # noqa: E402
    FabricCompiler,
)
from veritx_dse.application.presets import (  # noqa: E402
    build_typed_preset_request, preset_catalog, typed_preset_names,
)
from veritx_dse.model.compile_model import (  # noqa: E402
    fabric_intent_view,
)

PRESETS = {
    "dragonfly4": "dragonfly",
    "fat_tree4": "fat_tree",
    "flattened_butterfly16": "flattened_butterfly",
    "qtree7": "qtree",
    "tree4_7": "tree4",
}


def test_structured_presets_are_shipped():
    names = set(typed_preset_names())
    catalog = {p["preset_id"] for p in preset_catalog()}
    for preset in PRESETS:
        assert preset in names, preset
        assert preset in catalog, preset


def test_structured_presets_normalize_to_their_own_family():
    """The _product_wired predicate, structurally: each preset normalizes
    back to its family through the generation seam (no name matching)."""
    for preset, family in PRESETS.items():
        request = build_typed_preset_request(preset)
        view = fabric_intent_view(request)
        assert capability_family_label(view.topology) == family, preset


def test_structured_presets_compile():
    """Each preset compiles with topology, route and VC artifacts and a
    passing certificate — compile, route and verify in one assertion."""
    for preset in PRESETS:
        request = build_typed_preset_request(preset)
        compilation = FabricCompiler().compile(request)
        assert compilation.status == "COMPILED", (
            preset, getattr(compilation, "error", None))
        bundle = compilation.bundle
        assert bundle is not None, preset
        assert bundle.topology is not None, preset
        assert bundle.resolved_route is not None, preset
        assert bundle.vc_assignment is not None, preset
        assert compilation.certificate is not None, preset
        assert compilation.certificate.overall == "PASS", (
            preset, compilation.certificate.overall)
