"""deadlock_routing: certificate decisions through the pure seam.

deadlock_certificate() is the module's deep interface -- connectivity,
method dispatch, CDG acyclicity verdict, escape-VC requirement -- with
zero IO. These tests build tiny topologies/traffic matrices directly
(no mocks, no subprocesses) and assert the *decisions*, not the printing.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "veritx_dse" / "tools"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, str(TOOLS / f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dr():
    return _load("deadlock_routing")


def _ring(n):
    adj = {i: {(i - 1) % n, (i + 1) % n} for i in range(n)}
    return adj


def _full_traffic(n):
    return [[0.0 if i == j else 1.0 for j in range(n)] for i in range(n)]


class TestBooksimExactRouting:
    """The one-routing-truth seam: the certifier's `booksim` method must
    reproduce AnyNet::route() (anynet.cpp) hop-for-hop — the certificate
    is only meaningful if it evaluates the routes the simulator runs."""

    def test_booksim_matches_shortest_where_unique(self, dr):
        """On an ODD ring every shortest path is unique, so the
        BookSim-exact table must equal the legacy `shortest` table.
        (On an even ring ties exist and the tie-breaks differ — next test.)"""
        n = 5
        adj = _ring(n)
        T = _full_traffic(n)
        _, fh_b = dr.route(n, adj, T, method="booksim")
        _, fh_s = dr.route(n, adj, T, method="shortest")
        assert fh_b == fh_s

    def test_booksim_diverges_from_lexical_on_ties(self, dr):
        """Even ring, 1->4: clockwise (1,2,3,4) and counter-clockwise
        (1,0,5,4) are both 3 hops. shortest_route_table picks lexical-first
        (next hop 0); AnyNet::route's ascending-scan Dijkstra claimed 4
        via 2 first, so BookSim routes through 2. Both are minimal."""
        n = 6
        adj = _ring(n)
        T = _full_traffic(n)
        bestp_b, fh_b = dr.route(n, adj, T, method="booksim")
        bestp_s, fh_s = dr.route(n, adj, T, method="shortest")
        assert fh_b[(1, 4)] == 2
        assert fh_s[(1, 4)] == 0
        assert len(bestp_b[(1, 4)]) == len(bestp_s[(1, 4)]) == 4

    def test_booksim_tie_breaks_like_anynet(self, dr):
        """3x3 grid, s=0 -> t=8 has six length-4 paths. AnyNet::route()
        scans rlist ascending and relaxes with strict <, so the first
        predecessor to claim a node sticks: dist[5] is claimed via 2
        before 4 relaxes it, and dist[8] is claimed via 5 before 7
        relaxes it. Expected route: 0,1,2,5,8 — NOT the lexical-first
        (0,1,4,5,8) that shortest_route_table would pick."""
        adj = {
            0: {1, 3}, 1: {0, 2, 4}, 2: {1, 5},
            3: {0, 4, 6}, 4: {1, 3, 5, 7}, 5: {2, 4, 8},
            6: {3, 7}, 7: {4, 6, 8}, 8: {5, 7},
        }
        n = 9
        bestp, fh = dr.route(n, adj, _full_traffic(n), method="booksim")
        # hop counts must be true shortest distances
        d = dr.shortest_paths(adj, 0)[0]
        for t in range(1, n):
            path = bestp[(0, t)]
            assert len(path) - 1 == d[t], f"0->{t}: {path} not minimal"
        # the tie-break the C++ produces: first-improvement-sticks Dijkstra
        assert bestp[(0, 8)] == (0, 1, 2, 5, 8)

    def test_booksim_cdg_rings_cyclic_grid_acyclic(self, dr):
        """The booksim method flows through the same certificate core,
        and it reports the textbook result: ANY wraparound ring under
        minimal routing has a cyclic CDG (the dateline argument — ring
        traffic needs an escape VC regardless of ring parity), while a
        grid under min routing is acyclic. The winner check that cleared
        the 20260916 run used this exact code path."""
        for n in (5, 6):
            ring = _ring(n)
            bestp, _ = dr.route(n, ring, _full_traffic(n), method="booksim")
            acyclic, cycles, _ = dr.build_cdg_and_check(bestp, n, ring)
            assert not acyclic and cycles, f"ring{n} must be cyclic"

        grid = {
            0: {1, 3}, 1: {0, 2, 4}, 2: {1, 5},
            3: {0, 4, 6}, 4: {1, 3, 5, 7}, 5: {2, 4, 8},
            6: {3, 7}, 7: {4, 6, 8}, 8: {5, 7},
        }
        bestp, _ = dr.route(9, grid, _full_traffic(9), method="booksim")
        acyclic, _, _ = dr.build_cdg_and_check(bestp, 9, grid)
        assert acyclic

    def test_export_table_writes_csv(self, dr, tmp_path):
        fh = dr.booksim_first_hop_table(4, _ring(4))
        out = tmp_path / "cert"
        dr.export_route_table(fh, str(out))
        lines = out.with_suffix(".routes.csv").read_text().splitlines()
        assert lines[0] == "src,dst,next_hop"
        assert len(lines) == 1 + 4 * 3          # all-pairs minus diagonal
        assert "0,1,1" in lines


class TestConnectivity:
    def test_ring_is_connected(self, dr):
        assert dr.is_connected(_ring(4), 4)

    def test_split_graph_is_not(self, dr):
        adj = {0: {1}, 1: {0}, 2: {3}, 3: {2}}
        assert not dr.is_connected(adj, 4)


class TestCyclicVsAcyclic:
    def test_ring_dim_order_is_acyclic_pass(self, dr):
        """Ring + one-directional shortest routing => acyclic CDG => PASS."""
        n = 4
        adj = _ring(n)
        T = _full_traffic(n)
        bestp = dr.shortest_route_table(n, adj, T)
        acyclic, cycles, nchan = dr.build_cdg_and_check(bestp, n, adj)
        assert nchan == 2 * n            # each ring edge = 2 directed channels
        assert acyclic

    def test_all_clockwise_ring_cycles_fails(self, dr, monkeypatch):
        """Deterministic FAIL branch: route every flow clockwise around the
        ring. The four 2-hop flows close the channel-dependency cycle
        (0,1)->(1,2)->(2,3)->(3,0)->(0,1), so the cert must FAIL and
        demand an escape VC class. (Lexical shortest picks mixed
        directions on a ring -- which is exactly why it passes -- so the
        forced table is injected where shortest routing would sit.)"""
        n = 4
        adj = _ring(n)
        cyclic = {
            (0, 1): (0, 1), (1, 2): (1, 2), (2, 3): (2, 3), (3, 0): (3, 0),
            (0, 2): (0, 1, 2), (1, 3): (1, 2, 3),
            (2, 0): (2, 3, 0), (3, 1): (3, 0, 1),
        }
        # raw CDG check: cycle is detected
        acyclic, cycles, _nchan = dr.build_cdg_and_check(cyclic, n, adj)
        assert not acyclic
        assert cycles and len(cycles[0]) >= 4   # the 4-channel ring cycle

        # full cert through the seam with the forced table
        monkeypatch.setattr(dr, "shortest_route_table", lambda *a, **k: cyclic)
        cert = dr.deadlock_certificate(n, adj, _full_traffic(n),
                                       "ring4.anynet", method="shortest")
        cdg = cert["channel_dependency_graph"]
        assert cdg["acyclic"] is False
        assert cdg["verdict"].startswith("FAIL")
        assert cert["escape_vcs_required"] == 1


class TestCertificate:
    def test_ring_shortest_certificate_shape(self, dr):
        n = 4
        cert = dr.deadlock_certificate(n, _ring(n), _full_traffic(n),
                                       "ring4.anynet", method="shortest")
        assert cert["connected"] is True
        assert cert["method"] == "shortest"
        assert cert["routing_table_entries"] == n * (n - 1)
        assert cert["channel_dependency_graph"]["acyclic"] is True
        assert cert["channel_dependency_graph"]["verdict"].startswith("PASS")
        assert cert["escape_vcs_required"] == 0

    def test_escape_method_always_passes(self, dr):
        """Up*/Down* escape routing is deadlock-free by construction."""
        n = 6
        cert = dr.deadlock_certificate(n, _ring(n), _full_traffic(n),
                                       "ring6.anynet", method="escape")
        assert cert["channel_dependency_graph"]["acyclic"] is True
        assert cert["escape_vcs_required"] == 0

    def test_unknown_method_raises(self, dr):
        with pytest.raises(ValueError, match="unknown routing method"):
            dr.route(4, _ring(4), _full_traffic(4), method="bogus")

    def test_mclb_infeasible_raises_not_sysexit(self, dr, monkeypatch):
        """The IO-free seam raises; only main() converts to sys.exit."""
        def infeasible(n, adj, T, timeout):
            return (None, 0, {}, [], [], {})
        monkeypatch.setattr(dr, "solve_mclb", infeasible)
        with pytest.raises(dr.MclbInfeasible):
            dr.route(4, _ring(4), _full_traffic(4), method="mclb")

    def test_mclb_happy_path_through_seam(self, dr, monkeypatch):
        """solve_mclb success flows through route() without touching scipy
        (paths come back via the fake; the seam does the table + CDG)."""
        bestp_fake = {(0, 1): (0, 1), (1, 0): (1, 0)}
        def feasible(n, adj, T, timeout):
            return ("res", 2, {}, [], [], bestp_fake)
        monkeypatch.setattr(dr, "solve_mclb", feasible)
        bestp, fh = dr.route(4, _ring(4), _full_traffic(4), method="mclb")
        assert bestp == bestp_fake
        assert fh[(0, 1)] == 1 and fh[(1, 0)] == 0


class TestMainSemantics:
    def test_main_exits_1_on_infeasible(self, dr, tmp_path, monkeypatch, capsys):
        """main() owns exit semantics: infeasible MCLB -> exit 1, no cert."""
        anynet = tmp_path / "r.anynet"
        anynet.write_text("router 0 node 0 router 1\nrouter 1 node 1 router 0\n")
        mat = tmp_path / "T.mat"
        n = 2
        mat.write_text("\n".join(" ".join("0" if i == j else "1"
                                          for j in range(n))
                                 for i in range(n)) + "\n")
        def infeasible(*a, **k):
            return (None, 0, {}, [], [], {})
        monkeypatch.setattr(dr, "solve_mclb", infeasible)
        monkeypatch.setattr(sys, "argv",
                            ["deadlock_routing", "--anynet", str(anynet),
                             "--matrix", str(mat), "--out",
                             str(tmp_path / "cert"), "--method", "mclb"])
        with pytest.raises(SystemExit) as ei:
            dr.main()
        assert ei.value.code == 1
        assert not (tmp_path / "cert.json").exists()

    def test_main_writes_cert_json(self, dr, tmp_path, monkeypatch):
        anynet = tmp_path / "r.anynet"
        anynet.write_text("router 0 node 0 router 1\nrouter 1 node 1 router 0\n")
        mat = tmp_path / "T.mat"
        n = 2
        mat.write_text("\n".join(" ".join("0" if i == j else "1"
                                          for j in range(n))
                                 for i in range(n)) + "\n")
        monkeypatch.setattr(sys, "argv",
                            ["deadlock_routing", "--anynet", str(anynet),
                             "--matrix", str(mat), "--out",
                             str(tmp_path / "cert"), "--method", "shortest"])
        dr.main()
        import json
        cert = json.loads((tmp_path / "cert.json").read_text())
        assert cert["verdict-like field" if False else "connected"] is True
        assert cert["channel_dependency_graph"]["acyclic"] is True
