# New GEC shared-resource escape reference profile

`REFERENCE_GEC_SHARED_ESCAPE_V1` is **not the native hybrid_gec policy**.
Existing canonical GEC keeps its complete candidate-union rank proof unchanged.
Its phase/tap VC allocation is not reinterpreted as escape isolation.

Runnable from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tracks/t3-topology/dse python - <<'PY'
import json
from veritx_dse.model.gec_hybrid_route import GecHybridParams
from veritx_dse.model.topology_artifact import materialize_gec_hybrid
from veritx_dse.verification.gec_hybrid_escape import (
    PARTITION, TRANSITIONS, build_gec_shared_escape, verify_gec_shared_escape)
p = GecHybridParams(k=4, c=2, o=1, d=3, num_vcs=6)
t = materialize_gec_hybrid(k=4, concentration=2, o=1, d=3)
r = build_gec_shared_escape(p, t, partition=PARTITION, transitions=TRANSITIONS)
print(json.dumps(verify_gec_shared_escape(r, t), indent=2))
PY
```

The caller explicitly declares four **new reference** VCs: adaptive X=0,
adaptive Y=1, escape X=2, escape Y=3. The parent `num_vcs` describes source
candidate geometry, not this separate four-VC resource universe. This profile
ignores the native tap-slice VC allocation; it therefore cannot be projected
onto the existing simulator by inference.

Allowed concrete transitions are 0->0/1/2/3, 1->1/3, 2->2/3, 3->3.
Adaptive actions offer both legal geometric candidates; escape always uses the
actual shared wire and selected tap to jump to the destination coordinate,
X then Y. All injection contexts `(router, terminal, -1)` are explicit,
including local ejection. A fixed point over **every** offered adaptive/escape
action supplies all reachable concrete ingress-VC contexts. Impossible Y->X
contexts are not asserted reachable; missing or extra reachable contexts fail.

Construction binds actual geometry/resource IDs/tap order. Validation and
reload regenerate the complete relation against actual topology and parameters,
not a caller-supplied hash alone. The verifier checks deterministic escape
access from each nonlocal injection/transit context, concrete entry transitions,
closure after entry, termination from every context in at most two shared jumps,
and the complete escape CDG's acyclicity. Nodes are `(ResourceRef(kind,id),vc)`:
all taps contend for the SAME wire resource, never tap-labelled copies.

The certificate serializes its profile/topology identity, coverage counts and
explicit progress assumptions. Eventual escape selection, fair arbitration and
eventual sink credit availability are **assumptions**, not proved progress or
starvation guarantees. Buffer/allocator/protocol blocking, arbitrary adaptive
state, native execution/equivalence, area/timing and qualification remain outside
this standalone structural reference theorem. Dirty-tree tests are diagnostics.
