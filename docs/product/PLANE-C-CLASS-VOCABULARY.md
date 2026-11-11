# Plane C class vocabulary: control and coherence

Status: decided 2026-11-04. Authority: `model/multi_plane_vc.py`.

Plane C is the SROTA control plane (`model/control_plane.py`): a second
subnet carrying REQ/RSP/SNP on plain XY. Its traffic is therefore the
control/coherence family, not data traffic. The class→subnet binding must
say that explicitly instead of letting alphabetical round-robin decide.

## Decision

| Author class | Plane | Rule |
| --- | --- | --- |
| `control` | C (subnet 1) | exact name |
| `control:<suffix>` | C | prefix, e.g. `control:req` |
| `coherence` | C | exact name |
| `coherence:<suffix>` | C | prefix, e.g. `coherence:req` |
| `control_collective` | C | legacy compatibility only |
| anything else | D first, then C | sorted round-robin; first data class on D |

Matching is exact and case-sensitive. Class names are author-declared,
identity-bearing strings: `Control`, `CONTROL:req`, `controller`,
`controlx`, `coherencex` and `incoherent` are data classes. There is no
substring matching and no case folding, because either would silently
merge or move a class the author declared.

Only genuinely data classes are dealt round-robin. Pinning control (and
coherence) to Plane C is what prevents a data class from taking the
control plane merely because its name sorts first.

## Saved identities and the preset

`control_collective` is the spelling shipped by `srota32_plane_c` before
the namespace existed. It stays recognized so a project or request saved
with that class still compiles and binds to Plane C; it is not rewritten
in place. New authoring uses `control:<suffix>`.

The shipped preset now declares `control:collective` for its control
workload. Existing saved requests that still say `control_collective`
remain on Plane C through the legacy rule; only the preset's newly built
requests use the namespaced label. The class is a workload label, not a
fabric identity: both spellings bind the same role to the same plane.

## Consequences

- The shipped preset renders `class_subnet = {1,0}`: trace classes are
  sorted, so `control:collective` (subnet 1) precedes `tp_collective`
  (subnet 0).
- A fabric that leaves either plane with no class is refused with a typed
  error.
- The existing three-plus-class refusal is unchanged: Plane C has one
  secondary subnet and the profile executes one canonical class per plane.
  Changing which class is pinned does not relax that boundary.
- `is_coherence_class` remains the strict coherence predicate.
  `is_control_class` is the strict control predicate (including the
  legacy spelling), and `is_control_plane_class` is their union — the
  predicate the binding uses.
