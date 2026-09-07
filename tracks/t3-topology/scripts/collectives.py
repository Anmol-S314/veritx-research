"""Ring all-reduce traffic decomposition (plan.md Section 5, build step 7).

Pure function, no simulation: given a set of participant tile_ids and a
tensor size, returns the point-to-point edges the ring all-reduce algorithm
(scatter-reduce + all-gather) produces, aggregated over all steps.
"""


def ring_allreduce_pairs(participants: list, size_bytes: float) -> list:
    """Returns [(src_tile, dst_tile, total_bytes_on_that_edge), ...].

    Ring all-reduce with k participants runs 2*(k-1) steps, moving a
    size_bytes/k chunk along each ring edge (idx -> idx+1) at every step.
    Since the traffic matrix only cares about aggregate bytes per link
    (not per-timestep), each ring edge's contribution across all steps is
    summed into a single entry: 2*(k-1) * (size_bytes/k).

    `participants` order defines ring adjacency -- caller's choice (e.g.
    tile_id order). k=1 (nothing to reduce) returns no edges.
    """
    k = len(participants)
    if k <= 1:
        return []
    chunk = size_bytes / k
    steps = 2 * (k - 1)
    edge_bytes = steps * chunk
    return [
        (participants[i], participants[(i + 1) % k], edge_bytes)
        for i in range(k)
    ]


if __name__ == "__main__":
    # Unit test (plan.md Section 6, step 7): step count = 2(k-1), and total
    # bytes moved matches the standard ring all-reduce cost formula.
    parts = [3, 7, 11, 42]
    size = 1_000_000.0
    pairs = ring_allreduce_pairs(parts, size)
    k = len(parts)
    assert len(pairs) == k  # one aggregated edge per ring hop
    total_bytes = sum(b for _, _, b in pairs)
    expected_total = k * (2 * (k - 1)) * (size / k)  # = 2*(k-1)*size*k/k... see below
    assert abs(total_bytes - expected_total) < 1e-6, (total_bytes, expected_total)
    # Per-participant send volume (standard ring all-reduce comms cost):
    per_node_bytes = 2 * (k - 1) * (size / k)
    assert abs(pairs[0][2] - per_node_bytes) < 1e-6
    assert ring_allreduce_pairs([5], size) == []
    print("collectives.py selfcheck OK")