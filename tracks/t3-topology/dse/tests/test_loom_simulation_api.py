"""Phase-3 loom simulation API (track spec §3, acceptance).

Verifies the three simulation endpoints against synthetic series
artifacts: 200s carry source labels and the stated capacity formula,
and every refusal is typed with a spec-vocabulary code. No engine runs
here; the gateway reads tmp run dirs only — never Studio fixtures.

NOTE: these tests run against the real Phase-2 reader
(backend.channel_series) and pin the endpoint contract above it:
int channel ids, full provenance, descending utilization rows.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from veritx_dse.gateway.app import GatewayConfig, create_app
from veritx_dse.gateway import simulation_series

assert simulation_series._READER == "backend.channel_series", (
    f"expected the real reader, got {simulation_series._READER}")


def _series_doc(**overrides):
    doc = {
        "schema_version": 2,
        "run_hash": "run-good",
        "sample_period_cycles": 100,
        "num_windows": 4,
        "time_resets_observed": 0,
        "capacity_formula": (
            "flits_per_window/(window_cycles*"
            "link_capacity_flits_per_cycle)"),
        "link_capacity_flits_per_cycle": 1.0,
        "channels": [
            {"logical_channel_id": 27,
             "flits_per_window": [90, 98, 98, 96],
             "window_cycles": [100, 100, 100, 100],
             "stalls_per_window": [100, 120, 120, 140]},
            {"logical_channel_id": 1,
             "flits_per_window": [10, 12, 8, 10],
             "window_cycles": [100, 100, 100, 100],
             "stalls_per_window": None},
        ],
        "provenance": {"backend": "booksim-fork", "version": "test",
                         "binary_hash": "test-bin",
                         "input_hashes": ["test-input"]},
    }
    doc.update(overrides)
    return doc


@pytest.fixture()
def runs(tmp_path):
    root = tmp_path / "runs"
    good = root / "run-good"
    good.mkdir(parents=True)
    (good / "channel_timeseries.json").write_text(
        json.dumps(_series_doc()))
    nomeas = root / "run-nomeas"
    nomeas.mkdir(parents=True)
    return root


@pytest.fixture()
def client(runs):
    cfg = GatewayConfig(store_root=runs.parent / "store",
                        runs_root=runs)
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def test_load_measured_returns_labeled_table(client):
    resp = client.get(
        "/api/v1/loom/simulation/load?run=run-good&source=measured")
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["source"] == "measured"
    assert "capacity_formula" in body and body["capacity_formula"]
    ids = [c["logical_channel_id"] for c in body["channels"]]
    assert ids == [27, 1], ids  # descending util
    hot = body["channels"][0]
    assert hot["flits_total"] == 382
    assert hot["utilization"] == pytest.approx(382 / 400)
    assert hot["has_stalls"] is True
    assert body["channels"][1]["has_stalls"] is False


def test_load_derived_is_refused_not_interpolated(client):
    resp = client.get(
        "/api/v1/loom/simulation/load?run=run-good&source=derived")
    assert resp.status_code == 422, resp.text[:300]
    assert resp.json()["code"] == "UNSUPPORTED_SEMANTICS"


def test_load_bad_source_is_400(client):
    resp = client.get(
        "/api/v1/loom/simulation/load?run=run-good&source=guess")
    assert resp.status_code == 400, resp.text[:300]


def test_load_unknown_run_is_no_run(client):
    resp = client.get(
        "/api/v1/loom/simulation/load?run=run-deadbeef&source=measured")
    assert resp.status_code == 404, resp.text[:300]
    assert resp.json()["code"] == "NO_RUN"


def test_load_run_without_series_is_no_measured(client):
    resp = client.get(
        "/api/v1/loom/simulation/load?run=run-nomeas&source=measured")
    assert resp.status_code == 422, resp.text[:300]
    assert resp.json()["code"] == "NO_MEASURED"


def test_load_traversal_collapses_to_no_run(client):
    resp = client.get(
        "/api/v1/loom/simulation/load?run=..%2F..%2Fsecret&source=measured")
    assert resp.status_code == 404, resp.text[:300]
    assert resp.json()["code"] == "NO_RUN"


def test_series_returns_windows_and_source(client):
    resp = client.get("/api/v1/loom/simulation/series?run=run-good")
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["source"] == "measured"
    assert body["num_windows"] == 4
    assert body["cycles_sampled"] == 400
    assert body["time_resets_observed"] == 0
    assert len(body["channels"][0]["flits_per_window"]) == 4
    assert body["channels"][0]["window_cycles"] == [100, 100, 100, 100]


def test_series_derived_is_no_time_axis_not_flat_line(client):
    resp = client.get(
        "/api/v1/loom/simulation/series?run=run-good&source=derived")
    assert resp.status_code == 400, resp.text[:300]
    assert resp.json()["code"] == "NO_TIME_AXIS"


def test_link_detail_names_absent_breakdown(client):
    resp = client.get(
        "/api/v1/loom/simulation/link?run=run-good&channel=27")
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["utilization"] == pytest.approx(382 / 400)
    assert body["total_flits"] == 382
    assert body["stalls_total"] == 480
    assert body["breakdown"] is None
    assert body["breakdown_absence"]


def test_link_unknown_channel_is_404(client):
    resp = client.get(
        "/api/v1/loom/simulation/link?run=run-good&channel=XX-%3EYY")
    assert resp.status_code == 404, resp.text[:300]


def test_schema_mismatch_is_internal_never_a_shape(client, runs):
    # The reader's own contract: malformed stored bytes are an internal
    # error, never a client response shape. The gateway maps only the
    # four client refusal codes; anything else is a 500 with no payload.
    bad = runs / "run-badschema"
    bad.mkdir(parents=True)
    doc = _series_doc(schema_version=999)
    (bad / "channel_timeseries.json").write_text(json.dumps(doc))
    resp = client.get(
        "/api/v1/loom/simulation/load?run=run-badschema&source=measured")
    assert resp.status_code == 500, resp.text[:300]
    body = resp.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert "channels" not in body


def test_fixture_backend_is_refused_live(client, runs):
    trap = runs / "run-fixtrap"
    trap.mkdir(parents=True)
    doc = _series_doc(provenance={"backend": "fixture",
                                  "version": "test",
                                  "binary_hash": "test-bin",
                                  "input_hashes": ["test-input"]})
    (trap / "channel_timeseries.json").write_text(json.dumps(doc))
    resp = client.get(
        "/api/v1/loom/simulation/load?run=run-fixtrap&source=measured")
    assert resp.status_code == 409, resp.text[:300]
    assert resp.json()["code"] == "STALE_FIXTURE"


def test_link_and_table_agree_on_partial_windows(client, runs):
    # A trailing partial window makes sum(spans) != num_windows*period.
    # Table and link must use the same exact denominator (parent
    # regression: link_detail once used the stale nominal product).
    doc = _series_doc(
        num_windows=3,
        channels=[
            {"logical_channel_id": 27,
             "flits_per_window": [90, 98, 40],
             "window_cycles": [100, 100, 54],
             "stalls_per_window": None},
        ],
    )
    (runs / "run-good" / "channel_timeseries.json").write_text(
        json.dumps(doc))
    table = client.get(
        "/api/v1/loom/simulation/load",
        params={"run": "run-good", "source": "measured"}).json()
    link = client.get(
        "/api/v1/loom/simulation/link",
        params={"run": "run-good", "channel": "27"}).json()
    assert table["channels"][0]["utilization"] == link["utilization"]
    assert link["utilization"] == (228 / ((100 + 100 + 54) * 1.0))
