# Parameterized Chipyard project-source path

## Operator constraint

Code only. No compiler, build, elaboration, lint, simulation or tests were run
for this change. Earlier GEC heavy jobs remain stopped.

## Implemented code

- `product/chipyard_fabric.py` accepts an existing compiled bundle, rather than
  recompiling a request or selecting a fixed research profile.
- All fourteen target IDs share one topology-independent hardware implementation.
  Native IDs, router counts, sparse numbering, actual directed resources,
  shared-wire tap lists, concentration, asymmetric Fly ingress/ejection,
  packet fields, VC masks and buffer depths come from the supplied contract.
- Recorded private route entries, deterministic shared decisions and shape
  alternatives are expanded without a shortest-path fallback. Shape correlation
  is retained. Missing routes, ambiguous resource binding, loops, mismatched
  topology IDs and excessive alternative inventories refuse source export.
- `CompiledFabricPreview.scala` composes the parameterized queues, endpoint
  interfaces, physical resource pipelines and route replay. One pipeline is
  created per physical shared wire, not per tap. Each injection explicitly
  selects a recorded route alternative; per-hop VC masks remain in the contract.
- Route data is a hash-bound binary resource loaded with Java's standard
  library, not a generated giant Scala initializer. This avoids repeating the
  previous GEC static-method-size failure.
- Future normal revision creation freezes source inputs from the already
  available compilation bundle. Optional source-export refusal does not change
  the compiler's verdict. The source snapshot is hashed and revision-bound.
- `GET /api/v1/revisions/{revision_id}/chipyard-source/archive` packages that
  snapshot and source. It never recompiles, falls back to a research profile,
  or starts a worker/toolchain. Old revisions without a snapshot are refused;
  downloading source does not migrate them or launch a compile.
- The RTL page offers the revision-specific source download separately from
  native-profile source and from generated RTL/qualification.

## All fourteen

The same physical implementation accepts explicit contracts for mesh8x8,
torus8x8, cmesh, ring, gec_mecs, fly64, qtree, tree4, flatfly, srota8x8,
gec_hybrid, fattree, dragonflynew and kncube. These are target identities, not
hard-coded dimensions: actual graph/terminal geometry is always supplied.
The canonical compiler still owns which family intents it can produce; this
source path does not invent a new compiler intent or native proof for a family
that the compiler does not expose.

Offline source packaging accepts an existing normalized contract using
`python -m veritx_dse.product.chipyard_fabric --contract CONTRACT.json --out NEW.zip`.
This command is documented only and was not executed. It packages source; it
never invokes the compiler or a hardware tool. The output path must be new.

## Hardware scope — not final RTL qualification

The hardware is a SINGLE-flit, source-routed graph preview. It preserves
recorded path alternatives but does not implement the native adaptive/FIU/
telemetry/side-buffer selector. The injecting harness explicitly selects a path.
VC masks are retained; hardware keeps the current VC when allowed and otherwise
uses the lowest legal VC, not the compiled VC allocator.

Ready/valid pipelines, per-router VC queues and round-robin arbitration are
not the compiled per-input credit/iSLIP/packet-reservation pipeline. Multi-flit
framing, endpoint protocol adaptation, ordering, CDC, STA, electrical shared
wire semantics and cycle-equivalence are not implemented by this preview.
No native or final RTL support gate was widened on the strength of source alone.

## Written but unexecuted checks

`tests/test_chipyard_fabric.py` covers fourteen-ID serialization, exact resource
and sparse-router identity, shared wires without tap expansion, VC masks,
asymmetric/concentrated endpoints, lossless hashes, invalid paths and a
compiler-free adapter over an existing bundle fixture. These are source-path
checks, not tests of all fourteen native routing laws.

`tests/test_chipyard_sources.py` and `rtl/chipyard/tests/KNCubeSourceSpec.scala`
remain unexecuted. No passing runtime or qualification result is claimed.
