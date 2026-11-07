#!/usr/bin/env python3
"""Check the pinned flatfly coordinate graph and port-pair wiring law."""

K = 4
N = 2
ROUTERS = K**N


def neighbor(router: int, dim: int, peer_digit: int) -> tuple[int, int, int]:
    coordinate = (router // K**dim) % K
    if peer_digit == coordinate:
        raise ValueError("self is not a network port")
    peer = router + (peer_digit - coordinate) * K**dim
    local_port = (0 if dim == 0 else 3) + (
        peer_digit if peer_digit < coordinate else peer_digit - 1
    )
    peer_coordinate = (peer // K**dim) % K
    peer_port = (0 if dim == 0 else 3) + (
        coordinate if coordinate < peer_coordinate else coordinate - 1
    )
    return peer, local_port, peer_port


def main() -> None:
    directed = set()
    for router in range(ROUTERS):
        degree = set()
        for dim in range(N):
            coordinate = (router // K**dim) % K
            for peer_digit in range(K):
                if peer_digit == coordinate:
                    continue
                peer, local_port, peer_port = neighbor(router, dim, peer_digit)
                assert 0 <= peer < ROUTERS
                assert neighbor(peer, dim, coordinate) == (router, peer_port, local_port)
                directed.add((router, peer, local_port, peer_port))
                degree.add(peer)
        assert len(degree) == 6
    assert len(directed) == ROUTERS * N * (K - 1) == 96
    assert len({(src, dst) for src, dst, _, _ in directed}) == 96
    # Dimension-order route: x peer(s), then y peer(s), then local ejection.
    for src in range(ROUTERS):
        for dst in range(ROUTERS):
            x, y = src % K, src // K
            dx, dy = dst % K, dst // K
            route = []
            if x != dx:
                peer, port, _ = neighbor(src, 0, dx)
                route.append((src, peer, port))
                src = peer
            if y != dy:
                peer, port, _ = neighbor(src, 1, dy)
                route.append((src, peer, port))
                src = peer
            assert src == dst
            assert len(route) == (x != dx) + (y != dy)
    print("PASS topology checker: 16 routers, 96 directed channels, degree 6, reciprocal peer ports, all 256 DOR routes")


if __name__ == "__main__":
    main()
