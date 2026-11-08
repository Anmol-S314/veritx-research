#!/usr/bin/env python3
"""Check the pinned BookSim GEC-MECS16 shared-wire and route contract."""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE.parents[1] / "configs/supported16/gec_mecs16/config.cfg"


def read_config() -> dict[str, int]:
    text = CONFIG.read_text(encoding="utf-8")
    values: dict[str, int] = {}
    for key in ("k", "c", "o", "d", "num_vcs"):
        match = re.search(rf"^\s*{key}\s*=\s*(\d+)\s*;", text, re.MULTILINE)
        if not match:
            raise SystemExit(f"missing pinned config key {key!r} in {CONFIG}")
        values[key] = int(match.group(1))
    return values


def main() -> None:
    cfg = read_config()
    k, c, o, d, num_vcs = (cfg[key] for key in ("k", "c", "o", "d", "num_vcs"))
    if (k, c, o, d, num_vcs) != (4, 1, 1, 3, 3):
        raise SystemExit(f"unexpected gec_mecs16 dimensions: {cfg}")
    if o * d != k - 1 or num_vcs % d:
        raise SystemExit(f"nonconforming shared-wire/VC dimensions: {cfg}")

    routers = k * k
    row_wires = k * k * o
    col_wires = k * k * o
    row_drops: set[int] = set()
    col_drops: set[int] = set()
    checked_routes = 0
    max_hops = 0

    for src in range(routers):
        sx, sy = src % k, src // k
        row_peers = [sy * k + x for x in range(k) if x != sx]
        col_peers = [y * k + sx for y in range(k) if y != sy]
        assert len(row_peers) == d and len(col_peers) == d
        for dst in range(routers):
            dx, dy = dst % k, dst // k
            hops: list[tuple[int, int, int]] = []  # next router, tap/drop, VC low
            if src != dst:
                if sx != dx:
                    peer_idx = dx if dx < sx else dx - 1
                    tap = peer_idx % d
                    group = peer_idx // d
                    assert group < o
                    next_router = row_peers[tap]
                    assert next_router == sy * k + dx
                    vc_lo = tap * (num_vcs // d)
                    hops.append((next_router, tap, vc_lo))
                    row_drops.add(tap)
                    if sy != dy:
                        peer_idx = dy if dy < sy else dy - 1
                        tap = peer_idx % d
                        group = peer_idx // d
                        assert group < o
                        next_router = dy * k + dx
                        column_peers_after_row = [y * k + dx for y in range(k) if y != sy]
                        assert column_peers_after_row[tap] == next_router
                        vc_lo = tap * (num_vcs // d)
                        hops.append((next_router, tap, vc_lo))
                        col_drops.add(tap)
                else:
                    peer_idx = dy if dy < sy else dy - 1
                    tap = peer_idx % d
                    group = peer_idx // d
                    assert group < o
                    next_router = col_peers[tap]
                    assert next_router == dy * k + sx
                    vc_lo = tap * (num_vcs // d)
                    hops.append((next_router, tap, vc_lo))
                    col_drops.add(tap)
            assert not hops or hops[-1][0] == dst
            assert len(hops) <= 2
            checked_routes += 1
            max_hops = max(max_hops, len(hops))

    assert row_drops == set(range(d))
    assert col_drops == set(range(d))
    wire_count = row_wires + col_wires
    tap_connections = wire_count * d
    print(
        "PASS gec_mecs16 graph "
        f"routers={routers} shared_wires={wire_count} taps={tap_connections} "
        f"routes={checked_routes} row_drops={sorted(row_drops)} "
        f"column_drops={sorted(col_drops)} max_hops={max_hops}"
    )


if __name__ == "__main__":
    main()
