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
    #: The FULL certified chain (compile → lower → physical traffic →
    #: `select_booksim_profile`) accepts a design patched with the
    #: alternative value. False means every candidate carrying that value
    #: would compile and then be REFUSED at evaluation — never a valid
    #: optimization dimension, no matter how effective it looks.
    backend_executable: bool = True
    backend_note: str | None = None

    @property
    def qualified(self) -> bool:
        return self.compilable and self.effective and self.backend_executable


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


def _backend_executable(request: Any) -> tuple[bool, bool, str]:
    """(compiled, executable, note) through the certified chain.

    This is the EXACT gate `ProductService._assess_compilation` applies
    before any evaluation: compile → lower the workload → build the
    logical/physical traffic artifacts → `select_booksim_profile`.
    `compiled` is the compile stage alone; `executable` requires every
    stage including profile selection. A parameter whose patched designs
    are refused here can compile in a study and then fail at evaluation;
    qualification must not advertise it.
    """
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.backend.booksim_projection import (
        BookSimProjectionError, BookSimProjectionParents,
        select_booksim_profile,
    )
    from veritx_dse.model.vc_resource import vc_resources_from_assignment
    from veritx_dse.workload.intent_lowering import lower_compile_workload
    from veritx_dse.workload.messages import (
        LogicalMessageArtifactV2, LogicalMessageArtifactV3,
    )
    from veritx_dse.workload.traffic import (
        PhysicalTrafficArtifactV2, PhysicalTrafficArtifactV3,
    )
    try:
        from veritx_dse.workload.intent_lowering import (
            InvalidInput as _LoweringInvalid,
            MappingInvalid as _LoweringMappingInvalid,
            UnsupportedSchedule as _LoweringSchedule,
            UnsupportedSemantics as _LoweringSemantics,
        )
    except ImportError:                                 # pragma: no cover
        try:
            from veritx_dse.workload.lowering import (
                InvalidInput as _LoweringInvalid,
                MappingInvalid as _LoweringMappingInvalid,
                UnsupportedSchedule as _LoweringSchedule,
                UnsupportedSemantics as _LoweringSemantics,
            )
        except ImportError:                             # pragma: no cover
            _LoweringInvalid = _LoweringMappingInvalid = \
                _LoweringSchedule = _LoweringSemantics = Exception
    compilation = FabricCompiler().compile(request)
    if compilation.status != "COMPILED" or compilation.bundle is None:
        return False, False, (f"compile: {compilation.status}: "
                              f"{str(compilation.error)[:160]}")
    bundle = compilation.bundle
    try:
        lowered = lower_compile_workload(request)
        if lowered.unified_traffic_class is None:
            logical: Any = LogicalMessageArtifactV3(
                graph=lowered.graph,
                traffic_class_by_operation=lowered.traffic_class_by_operation)
            physical: Any = PhysicalTrafficArtifactV3(
                logical=logical,
                resolved_fabric=bundle.resolved_fabric,
                mapping=bundle.mapping, attachment=bundle.attachment,
                inventory=bundle.inventory,
                packet_format=bundle.packet_format)
        else:
            logical = LogicalMessageArtifactV2(
                graph=lowered.graph,
                traffic_class=lowered.unified_traffic_class)
            physical = PhysicalTrafficArtifactV2(
                logical=logical,
                resolved_fabric=bundle.resolved_fabric,
                mapping=bundle.mapping, attachment=bundle.attachment,
                inventory=bundle.inventory,
                packet_format=bundle.packet_format)
        parents = BookSimProjectionParents(
            resolved_fabric=bundle.resolved_fabric,
            topology=bundle.topology,
            attachment=bundle.attachment, mapping=bundle.mapping,
            vc_resource=vc_resources_from_assignment(bundle.vc_assignment),
            vc_assignment=bundle.vc_assignment,
            packet_format=bundle.packet_format,
            route=bundle.router_route, physical_traffic=physical)
        profile = select_booksim_profile(parents)
    except _LoweringInvalid as exc:
        return True, False, f"workload lowering refused: {str(exc)[:160]}"
    except (_LoweringMappingInvalid, _LoweringSchedule,
            _LoweringSemantics) as exc:
        return True, False, (f"workload lowering refused: "
                             f"{type(exc).__name__}: {str(exc)[:150]}")
    except BookSimProjectionError as exc:
        return True, False, f"certified profile refused: {str(exc)[:180]}"
    except Exception as exc:                            # noqa: BLE001
        return True, False, f"{type(exc).__name__}: {str(exc)[:150]}"
    return True, True, f"executable via {profile.profile_id}"


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


def _topology_family_backend_executability() -> tuple[dict[str, bool], str]:
    """Per-family truth from the FULL certified chain, keyed by family value.

    `_family_of` proves MATERIALIZATION. It does not prove that
    `select_booksim_profile` accepts the materialized fabric: concentrated
    mesh materializes and routes DOR_XY, and the certified profiles still
    refuse it (mesh-DOR pins seat_capacity 1; AnyNet requires
    ANYNET_MIN_HOPS).    Torus is refused even earlier — the certified mapping
    has no routing policy for it. This asks the real gate, once per family,
    so the capability payload cannot claim an execution that the product
    path refuses.

    Returns (truth, note) where truth maps family value →
    {"compiled": bool, "executable": bool}. `compiled` bounds
    accepted_values; `executable` bounds executable_values.
    """
    from veritx_dse.model.compile_model import TopologyFamily
    custom = getattr(TopologyFamily, "CUSTOM", None)
    truth: dict[str, dict[str, bool]] = {}
    refused: list[str] = []
    for family in TopologyFamily:
        if custom is not None and family is custom:
            truth[family.value] = {"compiled": False, "executable": False}
            refused.append(f"{family.value}: classification marker for an "
                           "explicit graph, not a materializable family")
            continue
        compiled, executable, note = _backend_executable(_base_request(
            topology_family=family.value, radix=None, concentration=None))
        truth[family.value] = {"compiled": compiled,
                               "executable": executable}
        if not executable:
            refused.append(f"{family.value}: {note}")
    note_text = ("full certified chain (compile → workload lowering → "
                 "select_booksim_profile); refused: "
                 + ("; ".join(refused) if refused else "none"))
    return truth, note_text


class _ProbeNoc:
    """Minimal duck-typed stand-in so `_family_of` can be asked directly.

    `_family_of` reads only `topology_family`; constructing a real NocConfig
    is unnecessary and would drag in unrelated validation.
    """

    def __init__(self, topology_family: Any) -> None:
        self.topology_family = topology_family


@lru_cache(maxsize=1)
def probe_parameters() -> dict[str, ParameterProbe]:
    """Probe every GUIDED parameter against the real compiler + projection."""
    out: dict[str, ParameterProbe] = {}
    base_id, base_note = _artifact_identity(_base_request())
    for name, baseline, alternative in _PROBE_CASES:
        alt_request = _base_request(**{name: alternative})
        alt_id, alt_note = _artifact_identity(alt_request)
        compilable = alt_id is not None
        effective = compilable and alt_id != base_id
        # Effectiveness alone is not qualification: a knob can change the
        # artifacts and still be refused by the certified profile (e.g.
        # concentration>1 changes the attachment; mesh-DOR refuses it).
        # Ask the same gate the product evaluation path applies.
        backend_executable, backend_note = False, "not probed"
        if compilable:
            _, backend_executable, backend_note = _backend_executable(
                alt_request)
        if not compilable:
            note = (f"a {name}={alternative!r} design does not compile: "
                    f"{alt_note}")
        elif not effective:
            note = (f"{name}={alternative!r} compiles but leaves EVERY "
                    "projection input identical, so the certified backend "
                    "would execute byte-identical work — the knob is "
                    "identity-only (it changes design_hash, not execution)")
        elif not backend_executable:
            note = (f"{name}={alternative!r} compiles and changes the "
                    "canonical artifacts, but the certified backend profile "
                    f"refuses the result: {backend_note}")
        else:
            note = (f"{name}={alternative!r} changes the canonical artifacts "
                    "the certified projection consumes")
        out[name] = ParameterProbe(
            name=name, baseline_value=baseline, alternative_value=alternative,
            compilable=compilable, effective=effective, note=note,
            backend_executable=backend_executable,
            backend_note=backend_note)
    topo_truth, topo_note = _topology_family_backend_executability()
    out["topology_family"] = ParameterProbe(
        name="topology_family", baseline_value="mesh", alternative_value="torus",
        compilable=True, effective=True,
        note=("per-family qualification is derived from the full certified "
              "chain; each materializable family changes the topology "
              "artifact"),
        backend_executable=bool(topo_truth.get("mesh")),
        backend_note=topo_note)
    # The per-family truth rides along so `capabilities` can narrow
    # `executable_values` without re-running the chain.
    out["_topology_family_truth"] = ParameterProbe(  # type: ignore[assignment]
        name="_topology_family_truth", baseline_value=None,
        alternative_value=None, compilable=True, effective=True,
        note=topo_note, backend_executable=True,
        backend_note=json.dumps(topo_truth, sort_keys=True))
    return out


def effectiveness_basis() -> str:
    """What the probe actually measured, for the payload's own honesty."""
    return ("prepare_booksim_input is a pure function of the projection inputs "
            f"{list(_PROJECTION_INPUTS)}; a parameter is EFFECTIVE when "
            f"patching it (base {PROBE_ENDPOINTS} endpoints, mesh) changes at "
            "least one of their canonical identities, COMPILABLE when the "
            "patched design compiles at all, and BACKEND_EXECUTABLE when the "
            "full certified chain (compile → workload lowering → "
            "select_booksim_profile) accepts the patched design — the same "
            "gate the product evaluation path applies before any run")


__all__ = ["ParameterProbe", "probe_parameters", "effectiveness_basis",
           "PROBE_ENDPOINTS"]
