"""Series production wiring: env trigger, options, product-id resolution.

Covers the last mile between a sampled execution and the loom API:
GatewayConfig reads the opt-in from the environment (absent = off,
garbage = startup refusal); BookSimRunOptions carries the four fields;
the gateway maps product run ids to their series hash through the
run's own evidence (unknown runs stay NO_RUN, unsampled runs are
NO_MEASURED, never zeros).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.application.errors import ErrorCode  # noqa: E402
from veritx_dse.application.federated_evaluator import (  # noqa: E402
    BookSimRunOptions,
)
from veritx_dse.gateway import simulation_series as gateway  # noqa: E402
from veritx_dse.gateway.app import config_from_env  # noqa: E402
from veritx_dse.product.service import (  # noqa: E402
    ProductConfig,
    ProductServiceError,
)


class _Product:
    def __init__(self, docs=None, error=None):
        self._docs = docs or {}
        self._error = error

    def run_evidence(self, run_id):
        if self._error is not None:
            raise self._error
        return {"documents": self._docs}


def _doc(run_hash):
    return {
        "schema_version": 3,
        "run_hash": run_hash,
        "sample_period_cycles": 100,
        "num_windows": 1,
        "time_resets_observed": 0,
        "capacity_formula": (
            "flits_per_window/(window_cycles*"
            "link_capacity_flits_per_cycle)"),
        "link_capacity_flits_per_cycle": 1,
        "channels": [{
            "logical_channel_id": 7,
            "flits_per_window": [10],
            "window_cycles": [100],
            "stalls_per_window": None,
            "queue_cycles_per_window": [5],
            "arb_wait_cycles_per_window": [1],
            "tx_flits_per_window": [10],
            "tx_busy_cycles_per_window": [40],
            "occupancy_flit_cycles_per_window": [200],
            "queue_max_per_window": [7],
            "arb_max_per_window": [3],
            "latency_max_per_window": [9],
            "occupancy_max_per_window": [4],
        }],
        "provenance": {
            "backend": "booksim", "version": "veritx-fork",
            "binary_hash": "0" * 64, "input_hashes": ["1" * 64],
        },
    }


def _store(tmp_path, run_hash):
    run_dir = tmp_path / run_hash
    run_dir.mkdir()
    (run_dir / "channel_timeseries.json").write_text(
        json.dumps(_doc(run_hash)))
    return tmp_path


def test_env_absent_means_off(monkeypatch):
    for key in ("VERITX_SERIES_SAMPLE_PERIOD",
                "VERITX_SERIES_LINK_WIDTH_BITS",
                "VERITX_SERIES_FLIT_WIDTH_BITS"):
        monkeypatch.delenv(key, raising=False)
    cfg = config_from_env()
    assert cfg.sample_period_cycles is None
    assert cfg.series_link_width_bits is None
    assert cfg.series_flit_width_bits is None


def test_env_valid_parses(monkeypatch):
    monkeypatch.setenv("VERITX_SERIES_SAMPLE_PERIOD", "500")
    monkeypatch.setenv("VERITX_SERIES_LINK_WIDTH_BITS", "128")
    monkeypatch.setenv("VERITX_SERIES_FLIT_WIDTH_BITS", "128")
    cfg = config_from_env()
    assert cfg.sample_period_cycles == 500
    assert cfg.series_link_width_bits == 128
    assert cfg.series_flit_width_bits == 128
    assert cfg.series_store_dir == cfg.runs_root


@pytest.mark.parametrize("key,value", [
    ("VERITX_SERIES_SAMPLE_PERIOD", "0"),
    ("VERITX_SERIES_SAMPLE_PERIOD", "-5"),
    ("VERITX_SERIES_SAMPLE_PERIOD", "many"),
    ("VERITX_SERIES_LINK_WIDTH_BITS", "wide"),
])
def test_env_garbage_refuses_startup(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=key):
        config_from_env()


def test_options_carry_the_opt_in():
    opts = BookSimRunOptions(
        sample_period_cycles=500, series_link_width_bits=128,
        series_flit_width_bits=128, series_store_dir="/tmp/store")
    assert opts.sample_period_cycles == 500
    assert BookSimRunOptions().sample_period_cycles is None


def test_product_config_carries_the_opt_in(tmp_path):
    cfg = ProductConfig(
        projects_root=tmp_path, sample_period_cycles=500,
        series_link_width_bits=128, series_flit_width_bits=128,
        series_store_dir=tmp_path / "store")
    assert cfg.sample_period_cycles == 500
    assert cfg.series_store_dir == tmp_path / "store"


def test_resolver_maps_product_run_to_its_hash():
    product = _Product(docs={
        "run/backend-evidence.json": {
            "evidence": {"series_run_hash": "ab" * 32},
            "attempt": {},
        },
    })
    assert gateway.resolve_series_run(product, "run-1") == (
        True, "ab" * 32)


def test_resolver_reports_unsampled_runs():
    product = _Product(docs={
        "run/backend-evidence.json": {
            "evidence": {"series_run_hash": None},
            "attempt": {},
        },
    })
    assert gateway.resolve_series_run(product, "run-1") == (True, None)


def test_resolver_unknown_run_is_not_found():
    product = _Product(error=ProductServiceError(
        ErrorCode.NOT_FOUND, "no such run"))
    assert gateway.resolve_series_run(product, "run-dead") == (
        False, None)


def test_resolver_corrupt_bundle_propagates():
    product = _Product(error=ProductServiceError(
        ErrorCode.CONFLICT, "bundle failed verification"))
    with pytest.raises(ProductServiceError):
        gateway.resolve_series_run(product, "run-1")


def test_product_run_serves_its_series(tmp_path):
    run_hash = "ab" * 32
    store = _store(tmp_path, run_hash)
    resolve = lambda rid: (True, run_hash) if rid == "run-1" else (False, None)  # noqa: E731
    table = gateway.load_table(store, "run-1", "measured",
                               resolve_run=resolve)
    assert table["run"] == "run-1"  # echo the requested id
    assert table["channels"][0]["logical_channel_id"] == 7
    detail = gateway.link_detail(store, "run-1", "7",
                                 resolve_run=resolve)
    assert detail["breakdown"]["queue_cycles"] == 5


def test_product_run_without_series_is_no_measured(tmp_path):
    store = _store(tmp_path, "ab" * 32)
    resolve = lambda rid: (True, None)  # noqa: E731
    with pytest.raises(gateway.SeriesRefusal) as exc:
        gateway.load_table(store, "run-1", "measured",
                            resolve_run=resolve)
    assert exc.value.code == "NO_MEASURED"


def test_unknown_run_stays_no_run(tmp_path):
    store = _store(tmp_path, "ab" * 32)
    resolve = lambda rid: (False, None)  # noqa: E731
    with pytest.raises(gateway.SeriesRefusal) as exc:
        gateway.load_table(store, "run-9", "measured",
                            resolve_run=resolve)
    assert exc.value.code == "NO_RUN"


def test_direct_hash_needs_no_resolver(tmp_path):
    run_hash = "ab" * 32
    store = _store(tmp_path, run_hash)
    table = gateway.load_table(store, run_hash, "measured")
    assert table["channels"][0]["flits_total"] == 10


def test_adapter_forwards_sampling_options(tmp_path, monkeypatch):
    # The production trigger: options carrying the opt-in must reach
    # execute_prepared_booksim unchanged; absent attrs default to off.
    from types import SimpleNamespace

    from test_backend_booksim_execution import _prepared
    from veritx_dse.backend.adapter import PreparedExecution
    from veritx_dse.backend.booksim_adapter import (
        BookSimAdapter,
        BookSimPreparation,
    )
    import veritx_dse.backend.booksim_execution as bx_mod
    import veritx_dse.backend.producer as producer_mod

    prepared = _prepared()
    native = BookSimPreparation(
        prepared=prepared, physical_traffic=None,
        message_artifact_id="m", physical_traffic_id="p",
        profile_id="x", config_hash="a" * 64, input_hash="b" * 64,
        realization_digest="c" * 64)
    wrapped = PreparedExecution(
        backend_id="booksim", projection_identity="i",
        qualification_identity="q", backend_config=None,
        backend_input=None, producer=None, native_prepared=native)
    seen = {}

    def fake_execute(**kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(bx_mod, "execute_prepared_booksim", fake_execute)
    monkeypatch.setattr(producer_mod, "resolve_producer_identity",
                        lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(producer_mod, "assert_pinned_producer",
                        lambda *a, **k: None)
    options = SimpleNamespace(
        binary=None, repo_root=None, run_dir=str(tmp_path),
        timeout=30, seed=None, sample_period_cycles=500,
        series_link_width_bits=128, series_flit_width_bits=128,
        series_store_dir=str(tmp_path / "store"))
    BookSimAdapter().execute(wrapped, options)
    assert seen["sample_period_cycles"] == 500
    assert seen["series_link_width_bits"] == 128
    assert seen["series_flit_width_bits"] == 128
    assert seen["series_store_dir"] == str(tmp_path / "store")
    bare = SimpleNamespace(binary=None, repo_root=None,
                           run_dir=str(tmp_path), timeout=30, seed=None)
    BookSimAdapter().execute(wrapped, bare)
    assert seen["sample_period_cycles"] is None
    assert seen["series_store_dir"] is None
