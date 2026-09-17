# ADR 0005 — Trusted execution config is separate from scientific intent

Status: accepted (2026-09-17)
Context: control-plane redesign §25. Today `t3`/`veritx` mix the two: env
vars pick binaries and container images at the same layer that users pick
topologies and traces. Agents (and web dispatch) inherit whatever the shell
had.

## Decision

Two disjoint configuration planes:

**Trusted execution config** (machine owner's domain; lives outside experiment
specs): binary paths, container image + digest, mount policy, allowed
execution environment (native/container), simulator environment variables,
resource limits. Sources: repo defaults (`core/paths.py`), explicit host
config, operator env — never an experiment spec or an agent tool call.

**Experiment spec** (scientific intent; agent-editable): workload id, system
shape, topology id, seeds, comparison intent. Specs reference simulators and
topologies **by registered ID** (`mesh_8x8`, `booksim`), never by path or
executable name. Unknown fields are rejected at the boundary, not normalized.

An agent (or web command) can therefore express any *scientific* intent while
being structurally unable to mount a host path, swap a binary, or inject
environment. Loosening that requires editing trusted config, which is a human
act.

## Consequences

- Registration lists (topologies, simulators) become the join point between
  the planes; they already exist (`model/presets.py` SWEEP_TOPOS, registry).
- "Works on my machine" moves into trusted config where it can be diffed and
  pinned (container digest per ADR 0006), instead of leaking into run specs.
- Every env-var override currently read near launch time must be classified:
  trusted (stay out of specs) or scientific (become a spec field with a
  default). No third category.
