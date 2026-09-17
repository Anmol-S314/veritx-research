"""Verified-PRD Integrity PR D — routing stopgap (§6.4, §7.1, §7.3).

Pins the routing-truth contract at the tool's CLI boundary (real
subprocess, no mocks):

  * default method is 'booksim' — the certificate evaluates the routes
    BookSim's AnyNet actually executes (the old 'mclb' default certified
    route set A while the simulator ran route set B);
  * the certified route table is persisted by default and its SHA256 is
    embedded in the certificate (evidence, not ephemera);
  * weighted AnyNet is REJECTED (exit 2, no certificate written): the
    replica is hop-count-based, BookSim's Dijkstra consumes link weights,
    so weighted topologies are uncertifiable on this path — fail closed,
    never certify an unweighted projection;
  * the escape-VC verdict language no longer implies BookSim implements
    escape discipline it does not have.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent

UNIT_RING = (
    "router 0 node 0 router 1\n"
    "router 1 node 1 router 2\n"
    "router 2 node 2 router 3\n"
    "router 3 node 3 router 0\n"
)

WEIGHTED_RING = (
    "router 0 node 0 router 1 15\n"
    "router 1 node 1 router 2\n"
    "router 2 node 2 router 3\n"
    "router 3 node 3 router 0\n"
)

RING_MATRIX = (
    "0 1 0 0\n"
    "0 0 1 0\n"
    "0 0 0 1\n"
    "1 0 0 0\n"
)


def _run_cert(tmp_path, anynet_text, args=()):
    anynet = tmp_path / "t.anynet"
    anynet.write_text(anynet_text)
    matrix = tmp_path / "t.mat"
    matrix.write_text(RING_MATRIX)
    return subprocess.run(
        [sys.executable, "-m", "veritx_dse.tools.deadlock_routing",
         "--anynet", str(anynet), "--matrix", str(matrix),
         "--out", str(tmp_path / "cert"), *args],
        capture_output=True, text=True, timeout=120,
        env={"PATH": __import__("os").environ["PATH"],
             "PYTHONPATH": str(DSE.parent.parent.parent / "tracks" / "t3-topology" / "dse"
                               if False else DSE)},
        cwd=str(DSE))


class TestDefaultMethodIsBooksim:
    def test_certificate_records_booksim_method(self, tmp_path):
        r = _run_cert(tmp_path, UNIT_RING)
        assert r.returncode == 0, r.stderr[-400:]
        cert = json.loads((tmp_path / "cert.json").read_text())
        assert cert["method"] == "booksim"

    def test_mclb_still_selectable_explicitly(self, tmp_path):
        r = _run_cert(tmp_path, UNIT_RING, ("--method", "mclb"))
        assert r.returncode == 0, r.stderr[-400:]
        cert = json.loads((tmp_path / "cert.json").read_text())
        assert cert["method"] == "mclb"


class TestRouteTablePersistence:
    def test_route_table_written_and_hashed_by_default(self, tmp_path):
        r = _run_cert(tmp_path, UNIT_RING)
        assert r.returncode == 0, r.stderr[-400:]
        table = tmp_path / "cert.routes.csv"
        assert table.is_file(), "certified route table must be persisted"
        header, first = table.read_text().splitlines()[:2]
        assert header == "src,dst,next_hop"
        assert len(first.split(",")) == 3
        cert = json.loads((tmp_path / "cert.json").read_text())
        rt = cert["route_table"]
        assert rt["sha256"] and len(rt["sha256"]) == 64
        assert rt["path"].endswith("cert.routes.csv")

    def test_no_export_flag_still_honored(self, tmp_path):
        r = _run_cert(tmp_path, UNIT_RING, ("--no-export-table",))
        assert r.returncode == 0, r.stderr[-400:]
        assert not (tmp_path / "cert.routes.csv").exists()
        cert = json.loads((tmp_path / "cert.json").read_text())
        assert "route_table" not in cert


class TestWeightedAnynetRejected:
    def test_weighted_topology_exit_2_no_certificate(self, tmp_path):
        r = _run_cert(tmp_path, WEIGHTED_RING)
        assert r.returncode == 2, f"expected rejection, got rc={r.returncode}"
        assert "weighted AnyNet" in r.stdout
        assert "w=15" in r.stdout
        assert not (tmp_path / "cert.json").exists(), \
            "no certificate may exist for an uncertifiable topology"

    def test_unit_weights_pass(self, tmp_path):
        """Weight tokens equal to 1 are fine — they match the replica."""
        unit_token = UNIT_RING.replace("router 1\n", "router 1 1\n", 1)
        r = _run_cert(tmp_path, unit_token)
        assert r.returncode == 0, r.stderr[-400:]


class TestVerdictLanguage:
    def test_acyclic_verdict_names_its_scope(self, tmp_path):
        """PR D: the verdict must not claim more than was checked — a
        physical-channel CDG check is not an escape-VC proof, because
        BookSim's min_anynet exposes all VCs on one hop with no escape
        discipline."""
        r = _run_cert(tmp_path, UNIT_RING)
        cert = json.loads((tmp_path / "cert.json").read_text())
        verdict = cert["channel_dependency_graph"]["verdict"]
        assert verdict.startswith("PASS")
        # Scope honesty: names the routing method whose CDG was checked.
        assert "booksim" in verdict.lower() or "min_anynet" in verdict.lower()
