#!/usr/bin/env python3
"""Shared-prefix KV multicast: broadcast one prefix to B requests, not B refetches. (T3 ext)

WHERE THIS COMES FROM. serving_multicast.py multicasts a KV *head* across the g query heads of
ONE request (the g-fold GQA win). This extends the SAME flit-fork primitive to a different,
larger axis of redundancy that agentic serving is exploding: a shared PREFIX (system prompt,
shared codebase, prior swarm turns) that B concurrent requests all attend to. Read it once from
HBM, broadcast over the idle NoC to all B requesting cores -> up to B-fold cut in prefix-KV DRAM
traffic, vs g-fold (~6-8) for GQA.

THE LOAD-BEARING ASSUMPTION (first, because it is the whole ballgame). The win exists ONLY when
the shared-prefix attention CANNOT be fused into one batched read. If the B requests are one
synchronous batch on one array, the prefix KV is read once and reused across the batch FOR FREE
-- multicast adds nothing. The B-fold redundancy appears when requests are SPREAD across tiles:
async agent swarms, different decode positions, disaggregated serving. This is the exact
analogue of T3's existing bound ("g is the ceiling of the HEAD-PARALLEL mapping"), moved to the
request axis. Unique contexts, or one fused batch -> no win. Never quote a B-fold without this.

THE MODEL. KV bytes are linear in token count, so all layer/head/dtype constants CANCEL -- the
saving depends only on B, the shared fraction f, and the GQA group g. Prefix P tokens (shared by
B requests), unique suffix S tokens per request, f = P/(P+S). Two independent redundancy axes,
they MULTIPLY:
    head axis    : g query heads re-read a KV head       -> GQA multicast removes factor g
    request axis : B requests re-read the shared prefix   -> prefix multicast removes B on prefix
  distinct KV read per step (n_kv-head, i.e. GQA-deduped):
    naive-naive (spread, neither) : g * B * (kv(P) + kv(S))
    GQA only                      :     B * (kv(P) + kv(S))
    prefix only                   : g * (kv(P) + B*kv(S))
    both                          :         kv(P) + B*kv(S)

  saving_prefix = B*(P+S)/(P+B*S) = B / (B - f*(B-1))
      f=0 -> 1 (no shared prefix) ; f=1 -> B (all shared) ; monotone in f and B ; in [1,B].
  saving_gqa = g  (flat in B and f -- the existing lever).

  CROSSOVER (prefix beats GQA): f* = B(g-1) / (g(B-1)) ; as B->inf, f* -> (g-1)/g.
  So prefix multicast wins once >~(g-1)/g of the KV is shared prefix (~89% at g=8) -- exactly the
  deep-shared-context / short-unique-generation regime of agent swarms.

HONESTY ON COMPRESSION (correcting an earlier overclaim of mine). The DRIVER of this lever is
the WORKLOAD: high concurrency B and a large shared fraction f, both exploding per the agentic
trend. KV *compression* is a SEPARATE axis: uniform compression scales absolute KV but leaves f
and the ratio UNCHANGED; non-uniform compression moves f either way depending on whether it hits
the shared prefix or the unique suffix harder. So this file does NOT claim "compression feeds the
prefix lever" -- it claims B and f do, and treats compression as a sign-ambiguous secondary axis.

    python3 scripts/prefix_multicast.py [--selfcheck]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import serving_multicast as sm          # Model, MODELS, GB -- reuse for the concrete anchor


def saving_prefix(B, f):
    """DRAM-read saving of prefix-multicast vs the spread-out per-request baseline. Depends ONLY
    on batch B and shared fraction f = P/(P+S) -- model constants cancel."""
    if B <= 0:
        return 0.0
    return B / (B - f * (B - 1))


def crossover_fraction(B, g):
    """Shared fraction above which prefix-multicast (scales with B) beats GQA-multicast (= g)."""
    if B <= 1:
        return 1.0
    return B * (g - 1) / (g * (B - 1))


def kv_reads(model, B, P, S):
    """Distinct KV bytes read per step under each sharing scheme (for the stacking check)."""
    kvP, kvS, g = model.kv_distinct(P), model.kv_distinct(S), model.g
    return {
        "naive_naive": g * B * (kvP + kvS),   # neither mechanism, requests spread across tiles
        "gqa_only":        B * (kvP + kvS),   # share KV head across g query heads (T3 today)
        "prefix_only": g * (kvP + B * kvS),   # share prefix across B requests
        "both":            (kvP + B * kvS),   # both -- the two factors multiply
    }


def _selfcheck():
    g = sm.MODELS[1].g                        # Llama-3-70B, g = 8

    # 1-4: known-answer endpoints, range [1,B], monotone in f
    for B in (2, 8, 64, 1000):
        assert abs(saving_prefix(B, 0.0) - 1.0) < 1e-9, (B, saving_prefix(B, 0.0))
        assert abs(saving_prefix(B, 1.0) - B) < 1e-6, (B, saving_prefix(B, 1.0))
        prev = 0.0
        for i in range(21):
            s = saving_prefix(B, i / 20)
            assert 1.0 - 1e-9 <= s <= B + 1e-6, (B, i / 20, s)
            assert s >= prev - 1e-9, "must be monotone increasing in f"
            prev = s
    # monotone in B at fixed f
    assert saving_prefix(64, 0.9) > saving_prefix(8, 0.9) > saving_prefix(2, 0.9)

    # 5-7: where B > g a real crossover exists in (0,1): prefix == GQA there, wins above/below
    for B in (16, 64, 1000):
        fstar = crossover_fraction(B, g)
        assert 0 < fstar < 1, (B, fstar)
        assert abs(saving_prefix(B, fstar) - g) < 1e-6, (B, fstar, saving_prefix(B, fstar), g)
        assert saving_prefix(B, fstar + 0.02) > g
        assert saving_prefix(B, fstar - 0.02) < g
    # where B <= g, prefix (max saving B) can NEVER strictly beat GQA (=g): crossover at/above 1
    for B in (2, 8):
        assert saving_prefix(B, 1.0) <= g + 1e-9
        assert crossover_fraction(B, g) >= 1.0 - 1e-9
    assert abs(crossover_fraction(10 ** 9, g) - (g - 1) / g) < 1e-6      # B->inf -> (g-1)/g

    # 8: the two mechanisms MULTIPLY; both-saving == g * prefix-saving
    m = sm.MODELS[1]
    B, P, S = 64, 200_000, 2_000
    f = P / (P + S)
    r = kv_reads(m, B, P, S)
    assert abs(r["naive_naive"] / r["gqa_only"] - g) < 1e-6                  # GQA removes factor g
    assert abs(r["gqa_only"] / r["both"] - saving_prefix(B, f)) < 1e-4       # prefix saving matches
    assert abs(r["naive_naive"] / r["both"] - g * saving_prefix(B, f)) < 1e-3  # they multiply

    # 9: model-INDEPENDENCE -- the saving RATIO is identical for two different models
    a = kv_reads(sm.MODELS[0], B, P, S)      # Llama-3-8B  (different layers/heads)
    b = kv_reads(sm.MODELS[1], B, P, S)      # Llama-3-70B
    assert abs(a["gqa_only"] / a["both"] - b["gqa_only"] / b["both"]) < 1e-9, "saving must be model-independent"

    print(f"selfcheck OK -- saving in [1,B]; f=0->1, f=1->B; crossover f*=B(g-1)/(g(B-1)) exact; "
          f"mechanisms multiply (g x prefix); model-independent")


def main():
    m = sm.MODELS[1]                          # Llama-3-70B, g=8 anchor (saving is model-independent)
    g = m.g
    print(f"\n  Shared-prefix KV multicast vs GQA multicast   (GQA group g={g})")
    print(f"  saving_prefix = B / (B - f*(B-1))   [f = shared-prefix fraction of the KV read]")
    print(f"  GQA lever is flat = g = {g}. Prefix lever scales with B once f clears the crossover.\n")

    print(f"  Crossover shared-fraction f* (prefix beats GQA); needs B > g={g} to have one:")
    print(f"    {'batch B':>8}  {'f*':>8}")
    for B in (4, 8, 16, 64, 256, 1024):
        fstar = crossover_fraction(B, g)
        cell = f"{fstar:>6.3f}" if fstar < 1 else "  never"    # B<=g: prefix can't beat GQA
        print(f"    {B:>8}  {cell:>8}")
    print(f"    {'B->inf':>8}  {(g - 1) / g:>6.3f}   = (g-1)/g\n")

    B = 64
    fstar = crossover_fraction(B, g)
    print(f"  Shared-fraction sweep at B={B}  (prefix lever vs the flat {g}x GQA lever):")
    print(f"    {'f':>6}  {'prefix':>8}  {'GQA':>6}   winner")
    for f in (0.0, 0.25, 0.50, 0.75, 0.833, round(fstar, 3), 0.95, 0.99, 1.0):
        sp = saving_prefix(B, f)
        win = "prefix" if sp > g + 0.05 else ("tie" if abs(sp - g) <= 0.05 else "GQA")
        mark = "  <- crossover" if abs(f - round(fstar, 3)) < 1e-9 else ""
        print(f"    {f:>6.3f}  {sp:>7.1f}x  {g:>5.0f}x   {win}{mark}")

    P, S = 200_000, 2_000                     # deep shared context, short per-turn generation
    f = P / (P + S)
    sp = saving_prefix(B, f)
    print(f"\n  HEADLINE (agent-swarm regime): {P // 1000}K shared context, {S // 1000}K unique/req, B={B}")
    print(f"    shared fraction f = {f:.3f}  ->  prefix multicast {sp:.0f}x  vs  GQA {g}x")
    print(f"    ~{sp / g:.0f}x more KV-read reduction than GQA, on the SAME flit-fork primitive,")
    print(f"    reading the resource everyone is drowning in (shared-context KV) once.")

    print(f"\n  BOUNDS: real ONLY when requests are spread across tiles (async swarms /")
    print(f"  disaggregated serving) so the prefix is not fused into one batched read; needs a")
    print(f"  genuinely shared prefix; bandwidth win not capacity; cross-CHIP sharing rides the")
    print(f"  scale-out fabric, not the NoC. Driver is B and f; compression is a sign-ambiguous")
    print(f"  secondary axis, not claimed. NEXT: cycle-accurate 2-D broadcast tree")
    print(f"  (prefix_broadcast_flitfork.py), known-answer gate: 1 inject -> B-1 deliveries.")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
