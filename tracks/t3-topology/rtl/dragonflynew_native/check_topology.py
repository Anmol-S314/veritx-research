#!/usr/bin/env python3
"""Check BookSim dragonflynew k=2,n=1 channel indices and route law."""
GROUPS = 9
PER_GROUP = 4
ROUTERS = GROUPS * PER_GROUP
P = 2
NON_TERMINAL_PORTS = 5

# Reproduce dragonfly.cpp's output-channel indexing in _BuildNet.
outputs = {}
for node in range(ROUTERS):
    for local_port in range(2 * P - 1):
        outputs[NON_TERMINAL_PORTS * node + local_port] = ("local", node, local_port)
    for global_port in range(P):
        outputs[NON_TERMINAL_PORTS * node + (2 * P - 1) + global_port] = (
            "global", node, global_port
        )
assert len(outputs) == 180

# Reproduce the local/global input-channel index formulas from _BuildNet.
inputs = {}
peers = {}
for node in range(ROUTERS):
    group = node // PER_GROUP
    local = node % PER_GROUP
    for input_port in range(2 * P - 1):
        if input_port < local:
            channel = (
                group * NON_TERMINAL_PORTS * PER_GROUP
                - (local - input_port) * NON_TERMINAL_PORTS
                + local * NON_TERMINAL_PORTS
                + (local - 1)
            )
        else:
            channel = (
                group * NON_TERMINAL_PORTS * PER_GROUP
                + local * NON_TERMINAL_PORTS
                + (input_port - local + 1) * NON_TERMINAL_PORTS
                + local
            )
        assert channel not in inputs
        inputs[channel] = ("local", node, input_port)
    for input_port in range(P):
        group_output = local * P + input_port
        if group > group_output:
            channel = (
                group_output * NON_TERMINAL_PORTS * PER_GROUP
                + (NON_TERMINAL_PORTS - P) * ((group - 1) // P)
                + (NON_TERMINAL_PORTS - P)
                + group - 1
            )
        else:
            channel = (
                (group_output + 1) * NON_TERMINAL_PORTS * PER_GROUP
                + (NON_TERMINAL_PORTS - P) * (group // P)
                + (NON_TERMINAL_PORTS - P)
                + group
            )
        assert channel not in inputs
        inputs[channel] = ("global", node, input_port)

assert set(outputs) == set(inputs), (set(outputs) - set(inputs), set(inputs) - set(outputs))
for channel, sink in inputs.items():
    kind, source, _ = outputs[channel]
    sink_kind, target, _ = sink
    assert kind == sink_kind
    assert source != target
    if kind == "local":
        assert source // PER_GROUP == target // PER_GROUP
    else:
        assert source // PER_GROUP != target // PER_GROUP
    peers[channel] = (source, target, kind)

assert len(peers) == 180
assert all((dst, src, kind) in {(d, s, k) for s, d, k in peers.values()}
           for src, dst, kind in peers.values())
edges = {tuple(sorted((src, dst))) for src, dst, _ in peers.values()}
assert len(edges) == 90
adj = [[] for _ in range(ROUTERS)]
for a, b in edges:
    adj[a].append(b)
    adj[b].append(a)
assert all(len(neighbors) == 5 for neighbors in adj)


def booksim_port(router: int, terminal_dest: int) -> int:
    """Transcribe dragonfly_port() port selection for this exact config."""
    group = router // PER_GROUP
    dst_group = terminal_dest // 8
    if dst_group == group:
        group_output = -1
        group_router = terminal_dest // P
    else:
        group_output = dst_group if group > dst_group else dst_group - 1
        group_router = group_output // P + group * PER_GROUP
    if terminal_dest // P == router:
        return terminal_dest % P
    if group_router == router:
        return P + (PER_GROUP - 1) + (group_output % P)
    if router < group_router:
        return (group_router % PER_GROUP) - 1 + P
    return (group_router % PER_GROUP) + P


def rtl_route_next(router: int, terminal_dest: int) -> int:
    """Mirror route_next() in the RTL for pairwise path equivalence checks."""
    src_group = router // PER_GROUP
    dst_group = terminal_dest // 8
    dst_router = terminal_dest // P
    if src_group == dst_group:
        return dst_router
    dst_rank = dst_group if dst_group < src_group else dst_group - 1
    src_gateway = src_group * PER_GROUP + dst_rank // P
    if router != src_gateway:
        return src_gateway
    src_rank = src_group if src_group < dst_group else src_group - 1
    return dst_group * PER_GROUP + src_rank // P


max_hops = 0
for src_terminal in range(72):
    src_router = src_terminal // P
    for dst_terminal in range(72):
        dst_router = dst_terminal // P
        current = src_router
        hops = 0
        global_hops = 0
        while current != dst_router:
            port = booksim_port(current, dst_terminal)
            assert 2 <= port <= 6, (src_terminal, dst_terminal, current, port)
            channel = NON_TERMINAL_PORTS * current + port - P
            source, target, kind = peers[channel]
            assert source == current
            assert rtl_route_next(current, dst_terminal) == target, (
                src_terminal, dst_terminal, current, target,
                rtl_route_next(current, dst_terminal)
            )
            if kind == "global":
                global_hops += 1
            else:
                assert kind == "local"
            current = target
            hops += 1
            assert hops <= 3, (src_terminal, dst_terminal, hops)
        expected_global_hops = int(src_router // PER_GROUP != dst_router // PER_GROUP)
        assert global_hops == expected_global_hops, (src_terminal, dst_terminal, global_hops)
        max_hops = max(max_hops, hops)

print(
    f"PASS dragonflynew graph routers={ROUTERS} undirected_links={len(edges)} "
    f"directed_channels={len(peers)} degree=5 all_pairs=5184 "
    f"routes=BookSim-min-group-hops max_hops={max_hops}"
)
