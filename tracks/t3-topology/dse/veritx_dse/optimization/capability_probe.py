"""capability_probe — ASK the compiler+projector what a knob actually does.

WHY THIS EXISTS (PRODUCT-CONVERGENCE-V1 PHASE 2.1)
==================================================

`NocConfig` accepting a field means the SCHEMA accepts it. It does not mean
the certified backend measures its effect. Advertising "accepts this field"
as "certified optimization can search this field" is how a UI ends up
offering knobs that silently do nothing.

THE DECISIVE TEST — byte identity of the projection's INPUTS
===========================================================

`prepare_booksim_input` is a PURE FUNCTION of `BookSimProjectionParents`:
topology, attachment, mapping, vc_resource, packet_format, route,
physical_traffic, resolved_fabric.

So if patching a parameter leaves every one of those artifact identities
unchanged, the backend bytes CANNOT differ. The parameter is IDENTITY-ONLY:
it changes `design_hash` while execution stays byte-identical. That is the
same defect class as the `priced_geodesic` false contract, and it is
detectable without spawning the binary.

Where the projection's own closed-world audit (`_AUDIT`) has no row for a
concept at all — no `channel_width`, no `arbiter_type`, no multicast
parameter, no RCU parameter — a field that can only reach the backend through
such a row is ineffective by construction. The probe does not need to know
that: comparing artifact identity already answers it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

#: Artifacts the certified projection is a pure function of. Read by name so a
#: bundle-shape change surfaces as a missing artifact, not a silent pass.
_PROJECTION_INPUTS = (
    "topology", "attachment", "mapping", "vc_assignment", "packet_format",
    "router_route", "resolved_fabric",
)

_HASH_ATTRS = (
    "topology_hash", "attachment_hash", "mapping_hash", "packet_format_hash",
    "route_table_hash", "resolved_fabric_hash", "artifact_hash",
)

#: A base request that compiles and projects cleanly for 16 endpoints.
PROBE_ENDPOINTS = 16


@dataclass(frozen=True)
class ParameterProbe:
    """What the real pipeline says about one parameter."""
    name: str
    baseline_value: Any
    alternative_value: Any
    compilable: bool
    effective: bool
    note: str

    @property
    def qualified(self) -> bool:
        return self.compilable and self.effective


def _base_request(**noc_overrides: Any) -> Any:
    import json as _json
    from pathlib import Path
    from veritx_dse.model.compile_model import CompileRequestV3

    from veritx_dse.core.paths import REPO as _REPO
    doc = _json.loads((_REPO / "tracks/t3-topology/examples/"
                       "dense_1b_16tiles-v3.json").read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    doc["agents"] = [{"kind": "compute_tile", "count": PROBE_ENDPOINTS,
                      "data_width": 256, "addr_width": 64,
                      "protocol": "AXI"}]
    doc["noc_config"] = dict(doc["noc_config"])
    doc["noc_config"].update({"topology_family": "mesh", "radix": None,
                              "concentration": None})
    doc["noc_config"].update(noc_overrides)
    return CompileRequestV3.from_dict(doc)


def _artifact_identity(request: Any) -> tuple[str | None, str]:
    """(identity, note). None identity means it did not compile."""
    from veritx_dse.application.fabric_compiler import FabricCompiler

    compilation = FabricCompiler().compile(request)
    if compilation.bundle is None:
        return None, f"{compilation.status}: {str(compilation.error)[:90]}"
    bundle = compilation.bundle
    parts: dict[str, Any] = {}
    for name in _PROJECTION_INPUTS:
        obj = getattr(bundle, name, None)
        if obj is None:
            parts[name] = "<absent>"
            continue
        digest = None
        for attr in _HASH_ATTRS:
            value = getattr(obj, attr, None)
            if value is None:
                continue
            digest = value() if callable(value) else value
            break
        parts[name] = digest if digest is not None else repr(sorted(
            (k, str(v)[:60]) for k, v in vars(obj).items()
            if not k.startswith("_")))[:400]
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True).encode()).hexdigest(), "compiled"


#: (parameter, baseline value, alternative value). The alternative is a value a
#: user would plausibly pick; effectiveness is judged by whether the CERTIFIED
#: pipeline produces different projection inputs for it.
_PROBE_CASES: tuple[tuple[str, Any, Any], ...] = (
    ("link_width", None, 128),
    ("concentration", None, 4),
    # radix=2 is a VALUE constraint (2x2=4 seats < 16 endpoints), not an
    # effectiveness failure. The probe uses a value that seats the base, so it
    # measures whether the knob reaches execution — the constraint is reported
    # separately.
    ("radix", None, 5),
    ("rcu_enabled", None, True),
    ("arbitration", None, "round_robin"),
    ("mcast_groups", None, 4),
    ("mcast_setup_cycles", None, 8),
)


@lru_cache(maxsize=1)
def probe_parameters() -> dict[str, ParameterProbe]:
    """Probe every GUIDED parameter against the real compiler + projection."""
    out: dict[str, ParameterProbe] = {}
    base_id, base_note = _artifact_identity(_base_request())
    for name, baseline, alternative in _PROBE_CASES:
        alt_id, alt_note = _artifact_identity(_base_request(**{name: alternative}))
        compilable = alt_id is not None
        effective = compilable and alt_id != base_id
        if not compilable:
            note = (f"a {name}={alternative!r} design does not compile: "
                    f"{alt_note}")
        elif not effective:
            note = (f"{name}={alternative!r} compiles but leaves EVERY "
                    "projection input identical, so the certified backend "
                    "would execute byte-identical work — the knob is "
                    "identity-only (it changes design_hash, not execution)")
        else:
            note = (f"{name}={alternative!r} changes the canonical artifacts "
                    "the certified projection consumes")
        out[name] = ParameterProbe(
            name=name, baseline_value=baseline, alternative_value=alternative,
            compilable=compilable, effective=effective, note=note)
    out["topology_family"] = ParameterProbe(
        name="topology_family", baseline_value="mesh", alternative_value="torus",
        compilable=True, effective=True,
        note=("materializable families are derived separately from the "
              "canonical materializer; each changes the topology artifact"))
    return out


def effectiveness_basis() -> str:
    """What the probe actually measured, for the payload's own honesty."""
    return ("prepare_booksim_input is a pure function of the projection inputs "
            f"{list(_PROJECTION_INPUTS)}; a parameter is EFFECTIVE when "
            f"patching it (base {PROBE_ENDPOINTS} endpoints, mesh) changes at "
            "least one of their canonical identities, and COMPILABLE when the "
            "patched design compiles at all")


__all__ = ["ParameterProbe", "probe_parameters", "effectiveness_basis",
           "PROBE_ENDPOINTS"]
