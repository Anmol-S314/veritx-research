"""Regime A / Regime B tile<->head assignment (plan.md Section 4)."""


def assign_heads_regime_a(num_heads: int, num_tiles: int) -> dict:
    """tiles_per_head <= 1: each tile owns one or more whole heads.
    Returns {tile_id: [head_ids]}.

    Deterministic tie-break: contiguous head blocks, the first `extra`
    tiles (by index) get one extra head."""
    if num_tiles > num_heads:
        raise ValueError("Regime A requires num_tiles <= num_heads")
    base = num_heads // num_tiles
    extra = num_heads % num_tiles
    assignment, h = {}, 0
    for tile_id in range(num_tiles):
        count = base + (1 if tile_id < extra else 0)
        assignment[tile_id] = list(range(h, h + count))
        h += count
    return assignment


def distribute_regime_b(num_heads: int, num_tiles: int) -> dict:
    """tiles_per_head > 1: split each head's work across multiple tiles.
    Returns {head_id: [tile_ids]}.

    Greedy, deterministic tie-break (plan.md Section 4 / Section 7 open
    decision): base = num_tiles // num_heads, extra = num_tiles % num_heads;
    the first `extra` heads (by index) get base+1 tiles, the rest get base.
    Matches the doc's worked N=72 example: 24 heads x 2 tiles + 8 heads x 3
    tiles = 72."""
    if num_tiles <= num_heads:
        raise ValueError("Regime B requires num_tiles > num_heads")
    base = num_tiles // num_heads
    extra = num_tiles % num_heads
    assignment, t = {}, 0
    for head_id in range(num_heads):
        count = base + (1 if head_id < extra else 0)
        assignment[head_id] = list(range(t, t + count))
        t += count
    return assignment


def distribute(num_heads: int, num_tiles: int) -> dict:
    """Dispatch to the correct regime based on tiles_per_head."""
    if num_tiles <= num_heads:
        return assign_heads_regime_a(num_heads, num_tiles)
    return distribute_regime_b(num_heads, num_tiles)


def split_sizes(total: int, k: int) -> list:
    """Split `total` into k slices. All slices equal except the last, which
    absorbs the remainder -- the deterministic convention plan.md uses for
    'K // k with remainder on last tile'."""
    if k <= 0:
        raise ValueError("k must be positive")
    base = total // k
    sizes = [base] * k
    sizes[-1] += total - base * k
    return sizes


if __name__ == "__main__":
    # Unit tests against the four target N values (plan.md Section 6, step 2)
    a16 = assign_heads_regime_a(32, 16)
    assert all(len(v) == 2 for v in a16.values()), a16
    a32 = assign_heads_regime_a(32, 32)
    assert all(len(v) == 1 for v in a32.values()), a32
    b64 = distribute_regime_b(32, 64)
    assert all(len(v) == 2 for v in b64.values()), b64
    b72 = distribute_regime_b(32, 72)
    counts = [len(v) for v in b72.values()]
    assert counts.count(2) == 24 and counts.count(3) == 8, counts
    assert sum(counts) == 72
    assert split_sizes(128, 3) == [42, 42, 44]
    print("distribute.py selfcheck OK")